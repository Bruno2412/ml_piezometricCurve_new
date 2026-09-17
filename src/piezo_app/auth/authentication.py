# -*- coding: utf-8 -*-
"""
auth/authentication.py — Connexion à Firebase Authentication et gestion
des comptes. Aucune interface ici : uniquement de la logique, appelée
par components/login.py.

Rôles gérés (stockés en "custom claims" Firebase, pas de base à part) :
  - 'global_master'   : voit toutes les sociétés (2 comptes prévus)
  - 'company_master'  : administre une seule société (1 par société)
  - 'user'            : utilisateur standard, rattaché à une société
"""

import firebase_admin
import requests
import streamlit as st
from firebase_admin import auth as fb_auth
from firebase_admin import credentials

from piezo_app.auth import permissions
from piezo_app.services.email_service import send_verification_email


def _init_firebase():
    """Initialise l'app Firebase Admin une seule fois."""
    if firebase_admin._apps:
        return firebase_admin.get_app()

    cred_dict = dict(st.secrets["firebase_service_account"])
    cred = credentials.Certificate(cred_dict)

    return firebase_admin.initialize_app(cred)


_init_firebase()

_API_KEY = st.secrets["firebase"]["api_key"]

_SIGN_IN_URL = (
    f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={_API_KEY}"
)


def approve_user(current_user: dict, target: dict) -> None:
    """
    Valide un compte utilisateur après confirmation de son email.

    Seul un global_master peut valider un compte.

    La validation :
        - exige que l'email soit vérifié ;
        - positionne approved=True ;
        - active le compte Firebase.

    Les droits pages restent inchangés et doivent être attribués
    explicitement par l'administrateur.
    """

    if current_user["role"] != permissions.GLOBAL_MASTER:
        raise PermissionError("Seul un global_master peut valider un compte.")

    user_record = fb_auth.get_user(target["uid"])

    if not user_record.email_verified:
        raise ValueError(
            "Impossible de valider ce compte : l'adresse email n'a pas encore été vérifiée."
        )

    claims = user_record.custom_claims or {}

    claims["approved"] = True

    fb_auth.set_custom_user_claims(
        user_record.uid,
        claims,
    )

    fb_auth.update_user(
        user_record.uid,
        disabled=False,
    )


class EmailNotVerifiedError(Exception):
    """Le mot de passe est correct mais l'email n'a pas encore été confirmé."""

    pass


class PendingApprovalError(Exception):
    """Le compte existe et l'email est confirmé, mais aucun rôle ne lui a
    encore été attribué par un administrateur."""

    pass


def generate_verification_link(
    email: str,
    action_url: str | None = None,
) -> str:
    """Génère le lien Firebase de vérification d'adresse email."""
    _init_firebase()

    if action_url:
        from firebase_admin.auth import ActionCodeSettings

        action_code_settings = ActionCodeSettings(
            url=action_url,
            handle_code_in_app=False,
        )

        return fb_auth.generate_email_verification_link(
            email,
            action_code_settings,
        )

    return fb_auth.generate_email_verification_link(email)


def authenticate(email: str, password: str) -> dict | None:
    """
    Authentifie un utilisateur auprès de Firebase Authentication.

    Flux :
        1. Email + mot de passe envoyés à Firebase REST API
        2. Firebase retourne un ID token
        3. L'ID token est vérifié avec Firebase Admin SDK
        4. Les custom claims sont récupérées depuis le token vérifié
        5. Le profil utilisateur est retourné

    Retourne None si l'authentification échoue.
    Lève EmailNotVerifiedError si l'email n'a pas encore été confirmé.
    Lève PendingApprovalError si aucun rôle n'a encore été attribué.
    """

    try:
        resp = requests.post(
            _SIGN_IN_URL,
            json={
                "email": email.strip(),
                "password": password,
                "returnSecureToken": True,
            },
            timeout=10,
        )

    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()

        id_token = data["idToken"]
        uid = data["localId"]

    except (ValueError, KeyError):
        return None

    try:
        decoded_token = fb_auth.verify_id_token(id_token)

    except Exception:
        return None

    if decoded_token.get("uid") != uid:
        return None

    try:
        user_record = fb_auth.get_user(uid)

    except Exception:
        return None

    if user_record.disabled:
        return None

    if not user_record.email_verified:
        raise EmailNotVerifiedError("Compte non confirmé. Vérifiez votre boîte mail.")

    claims = decoded_token

    role = claims.get("role")

    if role is None:
        raise PendingApprovalError(
            "Votre compte est en attente de validation par un administrateur."
        )

    return {
        "uid": uid,
        "email": user_record.email,
        "role": role,
        "company_id": claims.get("company_id"),
        "company_name": claims.get("company_name"),
        "pages": claims.get("pages"),
        "id_token": id_token,
        "refresh_token": data.get("refreshToken"),
        "expires_in": data.get("expiresIn"),
    }


def create_user(
    current_user,
    email,
    password,
    role,
    company_id=None,
    company_name=None,
):
    """Crée un compte Firebase et lui attribue son rôle."""

    if role == "company_master" and not permissions.can_assign_company_master(current_user):
        raise PermissionError("Seul un global_master peut attribuer le rôle company_master.")

    if not permissions.can_create_user_for(
        current_user,
        role,
        company_id,
    ):
        raise PermissionError(
            f"Le rôle '{current_user['role']}' ne peut pas créer un compte "
            f"'{role}'" + (f" pour la société '{company_id}'." if company_id else ".")
        )

    if role == "global_master" and company_id is not None:
        raise ValueError("Un global_master ne doit pas être rattaché à une société.")

    if role in ("company_master", "user") and company_id is None:
        raise ValueError("company_id est obligatoire pour ce rôle.")

    user_record = fb_auth.create_user(
        email=email,
        password=password,
    )

    claims = {
        "role": role,
    }

    if company_id is not None:
        claims["company_id"] = company_id
        claims["company_name"] = company_name

    fb_auth.set_custom_user_claims(
        user_record.uid,
        claims,
    )

    return user_record.uid


def list_users(current_user: dict):
    """Utilisateurs visibles selon le rôle de l'appelant."""

    if current_user["role"] not in (
        "global_master",
        "company_master",
    ):
        raise PermissionError("Droits insuffisants pour lister les utilisateurs.")

    result = []

    for u in fb_auth.list_users().iterate_all():
        claims = u.custom_claims or {}

        role = claims.get("role")

        if role is None:
            continue

        if (
            current_user["role"] == "company_master"
            and claims.get("company_id") != current_user["company_id"]
        ):
            continue

        result.append(
            {
                "uid": u.uid,
                "email": u.email,
                "role": role,
                "company_id": claims.get("company_id"),
                "company_name": claims.get("company_name"),
                "disabled": u.disabled,
                "pages": claims.get("pages"),
                "email_verified": u.email_verified,
                "approved": claims.get("approved", False),
            }
        )

    return result


def set_user_active(
    current_user,
    target: dict,
    is_active: bool,
):
    """Active ou désactive un compte Firebase."""

    if not permissions.can_modify_target(
        current_user,
        target,
    ):
        raise PermissionError("Droits insuffisants pour modifier ce compte.")

    fb_auth.update_user(
        target["uid"],
        disabled=not is_active,
    )


def set_user_pages(
    current_user,
    target: dict,
    pages: dict,
):
    """Définit les onglets auxquels target a accès."""

    if not permissions.can_modify_target(
        current_user,
        target,
    ):
        raise PermissionError("Droits insuffisants pour modifier les pages de ce compte.")

    existing_claims = fb_auth.get_user(target["uid"]).custom_claims or {}

    existing_claims["pages"] = {key: bool(pages.get(key, False)) for key in permissions.PAGE_KEYS}

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
    )


def list_companies():
    """
    Retourne la liste des sociétés connues dans les comptes Firebase.
    """

    companies = {}

    for user in fb_auth.list_users().iterate_all():
        claims = user.custom_claims or {}

        company_id = claims.get("company_id")
        company_name = claims.get("company_name")

        if not company_id or not company_name:
            continue

        companies[company_id] = {
            "company_id": company_id,
            "company_name": company_name,
        }

    return sorted(
        companies.values(),
        key=lambda company: company["company_name"].lower(),
    )
