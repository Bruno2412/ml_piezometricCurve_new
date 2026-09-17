# -*- coding: utf-8 -*-
"""
auth/authentication.py — Connexion à Firebase Authentication et gestion
des comptes.

Rôles :
  - global_master   : voit toutes les sociétés
  - company_master  : administre une société
  - user            : utilisateur standard
"""

import firebase_admin
import requests
import streamlit as st

from firebase_admin import auth as fb_auth
from firebase_admin import credentials

from piezo_app.auth import permissions


def _init_firebase():
    """
    Initialise Firebase Admin une seule fois.
    """

    if firebase_admin._apps:
        return firebase_admin.get_app()

    cred_dict = dict(
        st.secrets["firebase_service_account"]
    )

    cred = credentials.Certificate(
        cred_dict
    )

    return firebase_admin.initialize_app(
        cred
    )


_init_firebase()


_API_KEY = st.secrets["firebase"]["api_key"]

_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/"
    f"accounts:signInWithPassword?key={_API_KEY}"
)


class EmailNotVerifiedError(Exception):
    """
    Conservée pour compatibilité éventuelle.
    La vérification email n'est plus utilisée dans
    le flux d'inscription.
    """

    pass


class PendingApprovalError(Exception):
    """
    Le compte existe mais n'a pas encore été approuvé.
    """

    pass


def authenticate(
    email: str,
    password: str,
) -> dict | None:
    """
    Authentifie un utilisateur auprès de Firebase.

    Le compte doit :
        - exister ;
        - ne pas être désactivé ;
        - avoir approved=True ;
        - posséder un rôle.

    Retourne None si l'authentification échoue.

    Lève PendingApprovalError si le compte n'est pas encore approuvé.
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

    # ---------------------------------------------------------
    # Authentification Firebase échouée
    # ---------------------------------------------------------

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()

        id_token = data["idToken"]
        uid = data["localId"]

    except (ValueError, KeyError):
        return None

    # ---------------------------------------------------------
    # Vérification du token
    # ---------------------------------------------------------

    try:
        decoded_token = fb_auth.verify_id_token(
            id_token
        )

    except Exception:
        return None

    if decoded_token.get("uid") != uid:
        return None

    # ---------------------------------------------------------
    # Récupération du compte Firebase
    # ---------------------------------------------------------

    try:
        user_record = fb_auth.get_user(
            uid
        )

    except Exception:
        return None

    # ---------------------------------------------------------
    # Compte désactivé
    # ---------------------------------------------------------

    if user_record.disabled:
        raise PendingApprovalError(
            "Votre compte est en attente de validation "
            "par un administrateur."
        )

    # ---------------------------------------------------------
    # Custom claims
    # ---------------------------------------------------------

    claims = decoded_token

    role = claims.get("role")

    if role is None:
        raise PendingApprovalError(
            "Votre compte est en attente de validation "
            "par un administrateur."
        )

    # ---------------------------------------------------------
    # Approbation
    # ---------------------------------------------------------

    if not claims.get("approved", False):
        raise PendingApprovalError(
            "Votre compte est en attente de validation "
            "par un administrateur."
        )

    # ---------------------------------------------------------
    # Profil utilisateur
    # ---------------------------------------------------------

    return {
        "uid": uid,
        "email": user_record.email,
        "role": role,
        "company_id": claims.get("company_id"),
        "company_name": claims.get("company_name"),
        "pages": claims.get("pages"),
        "approved": claims.get("approved", False),
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
    """
    Crée un compte utilisateur depuis l'administration.

    Les comptes créés directement par un administrateur
    sont considérés comme approuvés.
    """

    if role == "company_master" and not permissions.can_assign_company_master(
        current_user
    ):
        raise PermissionError(
            "Seul un global_master peut attribuer le rôle "
            "company_master."
        )

    if not permissions.can_create_user_for(
        current_user,
        role,
        company_id,
    ):
        raise PermissionError(
            f"Le rôle '{current_user['role']}' ne peut pas créer "
            f"un compte '{role}'"
            + (
                f" pour la société '{company_id}'."
                if company_id
                else "."
            )
        )

    if role == "global_master" and company_id is not None:
        raise ValueError(
            "Un global_master ne doit pas être rattaché "
            "à une société."
        )

    if role in (
        "company_master",
        "user",
    ) and company_id is None:
        raise ValueError(
            "company_id est obligatoire pour ce rôle."
        )

    user_record = fb_auth.create_user(
        email=email,
        password=password,
    )

    claims = {
        "role": role,
        "approved": True,
    }

    if company_id is not None:
        claims["company_id"] = company_id
        claims["company_name"] = company_name

    fb_auth.set_custom_user_claims(
        user_record.uid,
        claims,
    )

    return user_record.uid


def list_users(
    current_user: dict,
):
    """
    Utilisateurs visibles selon le rôle de l'appelant.
    """

    if current_user["role"] not in (
        "global_master",
        "company_master",
    ):
        raise PermissionError(
            "Droits insuffisants pour lister les utilisateurs."
        )

    result = []

    for u in fb_auth.list_users().iterate_all():

        claims = u.custom_claims or {}

        role = claims.get("role")

        if role is None:
            continue

        if (
            current_user["role"] == "company_master"
            and claims.get("company_id")
            != current_user["company_id"]
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
                "approved": claims.get(
                    "approved",
                    False,
                ),
                "pages": claims.get("pages"),
            }
        )

    return result


def set_user_active(
    current_user: dict,
    target: dict,
    is_active: bool,
):
    """
    Active ou désactive un compte existant.

    Pour une première activation d'un utilisateur inscrit
    publiquement, utiliser activate_user() dans registration.py.
    """

    if not permissions.can_modify_target(
        current_user,
        target,
    ):
        raise PermissionError(
            "Droits insuffisants pour modifier ce compte."
        )

    fb_auth.update_user(
        target["uid"],
        disabled=not is_active,
    )


def set_user_pages(
    current_user: dict,
    target: dict,
    pages: dict,
):
    """
    Définit les pages accessibles à un utilisateur.
    """

    if not permissions.can_modify_target(
        current_user,
        target,
    ):
        raise PermissionError(
            "Droits insuffisants pour modifier les pages "
            "de ce compte."
        )

    existing_claims = (
        fb_auth
        .get_user(target["uid"])
        .custom_claims
        or {}
    )

    existing_claims["pages"] = {
        key: bool(
            pages.get(key, False)
        )
        for key in permissions.PAGE_KEYS
    }

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
    )


def list_companies():
    """
    Retourne la liste des sociétés connues.
    """

    companies = {}

    for user in fb_auth.list_users().iterate_all():

        claims = user.custom_claims or {}

        company_id = claims.get(
            "company_id"
        )

        company_name = claims.get(
            "company_name"
        )

        if not company_id or not company_name:
            continue

        companies[company_id] = {
            "company_id": company_id,
            "company_name": company_name,
        }

    return sorted(
        companies.values(),
        key=lambda company:
            company["company_name"].lower(),
    )