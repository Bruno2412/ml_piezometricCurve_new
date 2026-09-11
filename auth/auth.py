# -*- coding: utf-8 -*-
"""
Authentification multi-sociétés via Firebase Authentication, avec rôles
stockés en "custom claims" (pas besoin de base de données séparée) :
  - 'global_master'   : voit toutes les sociétés (2 comptes prévus)
  - 'company_master'  : administre une seule société (1 par société)
  - 'user'            : utilisateur standard, rattaché à une société

Deux briques Firebase utilisées :
  - Identity Toolkit REST API (clé API Web, non secrète) pour vérifier
    email + mot de passe au moment du login.
  - Firebase Admin SDK (clé de compte de service, secrète) pour créer
    des comptes et poser les rôles (custom claims) côté serveur.
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
    """Vérifie email + mot de passe via l'API Firebase. Retourne le
    profil utilisateur (avec rôle et société) si valide, sinon None."""
    try:
        resp = requests.post(
            _SIGN_IN_URL,
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    uid = resp.json()["localId"]
    user_record = fb_auth.get_user(uid)

    if user_record.disabled:
        return None

    claims = user_record.custom_claims or {}
    role = claims.get("role")
    if role is None:
        return None  # compte créé mais pas encore configuré avec un rôle

    return {
        "uid": uid,
        "email": user_record.email,
        "role": role,
        "company_id": claims.get("company_id"),
        "company_name": claims.get("company_name"),
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


def require_login():
    """Bloque l'accès au reste de l'app tant que l'utilisateur n'est pas
    authentifié. À appeler tout en haut de app_streamlit.py."""
    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user is not None:
        return

    st.title("Connexion — Expert Piézométrie Pro")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter")

    if submitted:
        user = authenticate(email, password)
        if user is None:
            st.error("Email ou mot de passe incorrect, ou compte non configuré.")
        else:
            st.session_state.user = user
            st.rerun()

    st.stop()


def render_user_badge():
    """Affiche l'utilisateur connecté + bouton de déconnexion dans la
    sidebar. À appeler juste après require_login()."""
    user = st.session_state.user
    label = f"{user['email']} ({user['role']})"
    if user.get("company_name"):
        label += f" — {user['company_name']}"
    st.sidebar.caption(f"Connecté : {label}")
    if st.sidebar.button("Se déconnecter"):
        st.session_state.user = None
        st.rerun()
