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


def _init_firebase():
    """Initialise l'app Firebase Admin une seule fois (Streamlit relance
    ce module à chaque rerun, il faut éviter la double init)."""
    if not firebase_admin._apps:
        cred_dict = dict(st.secrets["firebase_service_account"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)


_init_firebase()

_API_KEY = st.secrets["firebase"]["api_key"]
_SIGN_IN_URL = (
    f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
    f"?key={_API_KEY}"
)


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

    # Authentification Firebase échouée
    if resp.status_code != 200:
        return None

    try:
        data = resp.json()

        id_token = data["idToken"]
        uid = data["localId"]

    except (ValueError, KeyError):
        return None

    # ---------------------------------------------------------
    # Vérification cryptographique du token Firebase
    # ---------------------------------------------------------
    try:
        decoded_token = fb_auth.verify_id_token(id_token)

    except Exception:
        return None

    # Sécurité supplémentaire :
    # le UID du token doit correspondre au UID retourné par
    # l'API de connexion.
    if decoded_token.get("uid") != uid:
        return None

    # ---------------------------------------------------------
    # Récupération du compte Firebase
    # ---------------------------------------------------------
    try:
        user_record = fb_auth.get_user(uid)
    except Exception:
        return None

    if user_record.disabled:
        return None

    # ---------------------------------------------------------
    # Les custom claims viennent du token vérifié
    # ---------------------------------------------------------
    claims = decoded_token

    role = claims.get("role")

    if role is None:
        return None

    # ---------------------------------------------------------
    # Vérification de cohérence avec le compte Firebase
    # ---------------------------------------------------------
    return {
        "uid": uid,
        "email": user_record.email,
        "role": role,
        "company_id": claims.get("company_id"),
        "company_name": claims.get("company_name"),

        # Le token est conservé en session pour les vérifications
        # ultérieures.
        "id_token": id_token,
        "refresh_token": data.get("refreshToken"),
        "expires_in": data.get("expiresIn"),
    }


def create_user(email, password, role, company_id=None, company_name=None):
    """Crée un compte Firebase et lui attribue son rôle (+ société si
    applicable) via les custom claims."""
    if role == "global_master" and company_id is not None:
        raise ValueError("Un global_master ne doit pas être rattaché à une société.")
    if role in ("company_master", "user") and company_id is None:
        raise ValueError("company_id est obligatoire pour ce rôle.")

    user_record = fb_auth.create_user(email=email, password=password)

    claims = {"role": role}
    if company_id is not None:
        claims["company_id"] = company_id
        claims["company_name"] = company_name

    fb_auth.set_custom_user_claims(user_record.uid, claims)
    return user_record.uid


def list_users(current_user: dict):
    """Utilisateurs visibles selon le rôle de l'appelant : global_master
    voit tout, company_master voit uniquement sa société."""
    if current_user["role"] not in ("global_master", "company_master"):
        raise PermissionError("Droits insuffisants pour lister les utilisateurs.")

    result = []
    for u in fb_auth.list_users().iterate_all():
        claims = u.custom_claims or {}
        role = claims.get("role")
        if role is None:
            continue  # compte pas encore configuré, on l'ignore dans la liste

        if current_user["role"] == "company_master" and claims.get("company_id") != current_user["company_id"]:
            continue

        result.append({
            "uid": u.uid,
            "email": u.email,
            "role": role,
            "company_id": claims.get("company_id"),
            "company_name": claims.get("company_name"),
            "disabled": u.disabled,
        })
    return result


def set_user_active(uid: str, is_active: bool):
    fb_auth.update_user(uid, disabled=not is_active)
