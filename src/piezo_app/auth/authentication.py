# -*- coding: utf-8 -*-
"""
auth/authentication.py

Gestion de l'authentification Firebase et des comptes utilisateurs.

Architecture :
    - Firebase Admin SDK :
        * vérification des tokens
        * lecture/modification des comptes
        * gestion des custom claims
    - Firebase Authentication REST API :
        * connexion email / mot de passe

Rôles :
    - global_master
    - company_master
    - user

Claims utilisés :
    - role
    - company_id
    - company_name
    - pages

Le claim "approved" n'est plus utilisé.

Important :
    authenticate() n'est PAS mise en cache.
"""

import logging

import requests
import streamlit as st
import firebase_admin
from firebase_admin import auth as fb_auth
from firebase_admin import credentials

from piezo_app.auth import permissions


logger = logging.getLogger(__name__)


# ============================================================================
# INITIALISATION FIREBASE ADMIN
# ============================================================================

@st.cache_resource(ttl=600)
def _init_firebase():
    """
    Initialise Firebase Admin une seule fois par processus Streamlit.
    """

    # Si Firebase est déjà initialisé, on réutilise l'application existante.
    if firebase_admin._apps:
        return firebase_admin.get_app()

    try:
        cred_dict = dict(st.secrets["firebase_service_account"])
    except Exception as e:
        logger.exception(
            "Impossible de lire firebase_service_account dans st.secrets."
        )
        raise RuntimeError(
            "Configuration Firebase invalide : "
            "firebase_service_account est absent de st.secrets."
        ) from e

    try:
        cred = credentials.Certificate(cred_dict)
        return firebase_admin.initialize_app(cred)

    except Exception as e:
        logger.exception("Échec de l'initialisation Firebase Admin.")
        raise RuntimeError(
            "Impossible d'initialiser Firebase Admin."
        ) from e


# Initialisation au chargement du module.
_firebase_app = _init_firebase()


# ============================================================================
# CONFIGURATION FIREBASE AUTHENTICATION REST
# ============================================================================

try:
    _API_KEY = st.secrets["firebase"]["api_key"]
except Exception as e:
    logger.exception("firebase.api_key absent de st.secrets.")
    raise RuntimeError(
        "Configuration Firebase invalide : "
        "firebase.api_key est absent de st.secrets."
    ) from e


_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/"
    f"accounts:signInWithPassword?key={_API_KEY}"
)


# ============================================================================
# EXCEPTIONS DE COMPATIBILITÉ
# ============================================================================

class EmailNotVerifiedError(Exception):
    """
    Conservée pour compatibilité avec d'anciens imports.

    La vérification de l'email n'est pas utilisée pour bloquer la connexion.
    """

    pass


class PendingApprovalError(Exception):
    """
    Conservée pour compatibilité avec d'anciens imports.

    Le mécanisme actuel repose sur :
        - disabled
        - role
        - pages
    """

    pass


# ============================================================================
# AUTHENTIFICATION
# ============================================================================

def authenticate(
    email: str,
    password: str,
) -> dict | None:
    """
    Authentifie un utilisateur Firebase.

    Étapes :
        1. Firebase Authentication REST API
        2. récupération du ID token
        3. vérification du ID token avec Firebase Admin
        4. récupération du compte Firebase
        5. contrôle disabled
        6. récupération des custom claims
        7. contrôle du rôle

    Retourne un dictionnaire utilisateur ou None.

    Aucun cache :
        cette fonction manipule des identifiants, tokens et données
        de session utilisateur.
    """

    email = (email or "").strip()

    if not email or not password:
        return None

    # ------------------------------------------------------------------
    # 1. Connexion Firebase Authentication
    # ------------------------------------------------------------------

    try:
        response = requests.post(
            _SIGN_IN_URL,
            json={
                "email": email,
                "password": password,
                "returnSecureToken": True,
            },
            timeout=15,
        )

    except requests.RequestException as e:
        logger.error(
            "Erreur réseau lors de la connexion Firebase pour %s : %s",
            email,
            e,
        )
        return None

    # ------------------------------------------------------------------
    # 2. Vérification de la réponse Firebase
    # ------------------------------------------------------------------

    if response.status_code != 200:
        try:
            error_data = response.json()
            firebase_error = (
                error_data
                .get("error", {})
                .get("message", "UNKNOWN_ERROR")
            )
        except ValueError:
            firebase_error = response.text

        logger.warning(
            "Connexion Firebase refusée pour %s — HTTP %s — %s",
            email,
            response.status_code,
            firebase_error,
        )

        return None

    # ------------------------------------------------------------------
    # 3. Extraction du token
    # ------------------------------------------------------------------

    try:
        data = response.json()

        id_token = data["idToken"]
        uid = data["localId"]

    except (ValueError, KeyError) as e:
        logger.error(
            "Réponse Firebase Authentication invalide pour %s : %s",
            email,
            e,
        )
        return None

    # ------------------------------------------------------------------
    # 4. Vérification du token avec Firebase Admin
    # ------------------------------------------------------------------

    try:
        decoded_token = fb_auth.verify_id_token(
            id_token,
            app=_firebase_app,
        )

    except Exception as e:
        logger.error(
            "Échec verify_id_token pour %s : %s",
            email,
            e,
        )
        return None

    # Vérification de cohérence UID.
    if decoded_token.get("uid") != uid:
        logger.error(
            "UID incohérent pour %s : token=%s / login=%s",
            email,
            decoded_token.get("uid"),
            uid,
        )
        return None

    # ------------------------------------------------------------------
    # 5. Récupération du compte Firebase
    # ------------------------------------------------------------------

    try:
        user_record = fb_auth.get_user(
            uid,
            app=_firebase_app,
        )

    except fb_auth.UserNotFoundError:
        logger.warning(
            "Compte Firebase introuvable après authentification : %s",
            email,
        )
        return None

    except Exception as e:
        logger.error(
            "Échec get_user pour %s : %s",
            email,
            e,
        )
        return None

    # ------------------------------------------------------------------
    # 6. Compte désactivé
    # ------------------------------------------------------------------

    if user_record.disabled:
        logger.info(
            "Connexion refusée : compte désactivé — %s",
            email,
        )
        return None

    # ------------------------------------------------------------------
    # 7. Custom claims
    # ------------------------------------------------------------------

    # On utilise les claims du compte Firebase.
    #
    # Le token contient normalement les mêmes claims, mais les custom
    # claims peuvent avoir été modifiés récemment. Le record Firebase
    # constitue ici la source de vérité côté serveur.

    claims = user_record.custom_claims or {}

    role = claims.get("role")

    if not role:
        logger.warning(
            "Connexion refusée : aucun rôle Firebase pour %s (uid=%s)",
            email,
            uid,
        )
        return None

    # ------------------------------------------------------------------
    # 8. Construction de la session utilisateur
    # ------------------------------------------------------------------

    pages = claims.get("pages")

    if pages is None:
        pages = {}

    user = {
        "uid": uid,
        "email": user_record.email or email,
        "role": role,
        "company_id": claims.get("company_id"),
        "company_name": claims.get("company_name"),
        "pages": pages,
        "id_token": id_token,
        "refresh_token": data.get("refreshToken"),
        "expires_in": data.get("expiresIn"),
    }

    logger.info(
        "Connexion réussie : %s — rôle=%s — société=%s",
        user["email"],
        role,
        user.get("company_id"),
    )

    return user


# ============================================================================
# RAFRAÎCHISSEMENT DE SESSION
# ============================================================================

def refresh_session_user(user: dict) -> dict | None:
    """
    Actualise les informations Firebase d'un utilisateur déjà connecté.

    Vérifie :
        - existence du compte
        - disabled
        - rôle
        - société
        - pages

    En cas d'erreur réseau temporaire, la session existante est conservée.
    """

    if not user:
        return None

    uid = user.get("uid")

    if not uid:
        return None

    try:
        record = fb_auth.get_user(
            uid,
            app=_firebase_app,
        )

    except fb_auth.UserNotFoundError:
        logger.warning(
            "refresh_session_user : utilisateur introuvable : %s",
            uid,
        )
        return None

    except Exception as e:
        logger.warning(
            "refresh_session_user : erreur Firebase transitoire : %s",
            e,
        )

        # On conserve la session existante en cas d'erreur transitoire.
        return user

    # ------------------------------------------------------------------
    # Compte désactivé
    # ------------------------------------------------------------------

    if record.disabled:
        logger.info(
            "refresh_session_user : compte désactivé : %s",
            uid,
        )
        return None

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    claims = record.custom_claims or {}

    role = claims.get("role")

    if not role:
        logger.warning(
            "refresh_session_user : aucun rôle pour %s",
            uid,
        )
        return None

    pages = claims.get("pages") or {}

    return {
        **user,
        "email": record.email or user.get("email"),
        "role": role,
        "company_id": claims.get("company_id"),
        "company_name": claims.get("company_name"),
        "pages": pages,
    }


# ============================================================================
# CACHE DES UTILISATEURS
# ============================================================================

@st.cache_data(ttl=120)
def _fetch_all_users_raw():
    """
    Récupère les comptes Firebase.

    Cette fonction est la seule partie du listing utilisateurs mise en cache.
    """

    result = []

    for user in fb_auth.list_users(
        app=_firebase_app
    ).iterate_all():

        claims = user.custom_claims or {}

        result.append(
            {
                "uid": user.uid,
                "email": user.email,
                "role": claims.get("role"),
                "company_id": claims.get("company_id"),
                "company_name": claims.get("company_name"),
                "disabled": user.disabled,
                "pages": claims.get("pages") or {},
            }
        )

    return result


def invalidate_users_cache():
    """
    Invalide le cache des utilisateurs.
    """

    _fetch_all_users_raw.clear()


# ============================================================================
# LISTE DES UTILISATEURS
# ============================================================================
@st.cache_data(ttl=600)
def list_users(current_user: dict):
    """
    Retourne les utilisateurs visibles par l'utilisateur courant.
    """

    role = current_user.get("role")

    if role not in permissions.ADMIN_ROLES:
        raise PermissionError(
            "Droits insuffisants pour lister les utilisateurs."
        )

    result = [
        user
        for user in _fetch_all_users_raw()
        if user.get("role") is not None
    ]

    if role == permissions.COMPANY_MASTER:
        company_id = current_user.get("company_id")

        result = [
            user
            for user in result
            if user.get("company_id") == company_id
        ]

    return result


# ============================================================================
# CRÉATION UTILISATEUR
# ============================================================================

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
    """

    if (
        role == permissions.COMPANY_MASTER
        and not permissions.can_assign_company_master(current_user)
    ):
        raise PermissionError(
            "Seul un global_master peut attribuer le rôle company_master."
        )

    if not permissions.can_create_user_for(
        current_user,
        role,
        company_id,
    ):
        raise PermissionError(
            f"Le rôle '{current_user.get('role')}' ne peut pas créer "
            f"un compte '{role}'"
            + (
                f" pour la société '{company_id}'."
                if company_id
                else "."
            )
        )

    if (
        role == permissions.GLOBAL_MASTER
        and company_id is not None
    ):
        raise ValueError(
            "Un global_master ne doit pas être rattaché à une société."
        )

    if (
        role in (
            permissions.COMPANY_MASTER,
            permissions.USER,
        )
        and company_id is None
    ):
        raise ValueError(
            "company_id est obligatoire pour ce rôle."
        )

    user_record = fb_auth.create_user(
        email=email,
        password=password,
        app=_firebase_app,
    )

    claims = {
        "role": role,
    }

    if company_id is not None:
        claims["company_id"] = company_id
        claims["company_name"] = company_name

    try:
        fb_auth.set_custom_user_claims(
            user_record.uid,
            claims,
            app=_firebase_app,
        )

    except Exception:
        try:
            fb_auth.delete_user(
                user_record.uid,
                app=_firebase_app,
            )
        except Exception:
            logger.exception(
                "Impossible de supprimer le compte Firebase orphelin."
            )

        raise

    invalidate_users_cache()

    return user_record.uid


# ============================================================================
# ACTIVATION / DÉSACTIVATION
# ============================================================================

def set_user_active(
    current_user: dict,
    target: dict,
    is_active: bool,
):
    """
    Active ou désactive un compte existant.
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
        app=_firebase_app,
    )

    invalidate_users_cache()


# ============================================================================
# MODIFICATION DU RÔLE
# ============================================================================

def set_user_role(
    current_user: dict,
    target: dict,
    new_role: str,
    new_company_id: str | None = None,
    new_company_name: str | None = None,
):
    """
    Modifie le rôle d'un compte existant.
    """

    if not permissions.can_modify_target(
        current_user,
        target,
    ):
        raise PermissionError(
            "Droits insuffisants pour modifier ce compte."
        )

    if new_role == permissions.GLOBAL_MASTER:
        raise PermissionError(
            "Le rôle global_master ne peut pas être attribué depuis "
            "cet écran."
        )

    if (
        new_role == permissions.COMPANY_MASTER
        and not permissions.can_assign_company_master(current_user)
    ):
        raise PermissionError(
            "Seul un global_master peut attribuer le rôle company_master."
        )

    target_company_id = (
        new_company_id
        if new_company_id is not None
        else target.get("company_id")
    )

    target_company_name = (
        new_company_name
        if new_company_name is not None
        else target.get("company_name")
    )

    if not permissions.can_create_user_for(
        current_user,
        new_role,
        target_company_id,
    ):
        raise PermissionError(
            f"Le rôle '{current_user.get('role')}' ne peut pas attribuer "
            f"le rôle '{new_role}' à cette société."
        )

    if (
        new_role in (
            permissions.COMPANY_MASTER,
            permissions.USER,
        )
        and target_company_id is None
    ):
        raise ValueError(
            "company_id est obligatoire pour ce rôle."
        )

    existing_record = fb_auth.get_user(
        target["uid"],
        app=_firebase_app,
    )

    existing_claims = existing_record.custom_claims or {}

    existing_claims["role"] = new_role

    if target_company_id is None:
        existing_claims.pop("company_id", None)
        existing_claims.pop("company_name", None)
    else:
        existing_claims["company_id"] = target_company_id
        existing_claims["company_name"] = target_company_name

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
        app=_firebase_app,
    )

    invalidate_users_cache()


# ============================================================================
# MODIFICATION DES PAGES
# ============================================================================

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
            "Droits insuffisants pour modifier les pages de ce compte."
        )

    normalized = permissions.normalize_pages(pages)

    grantable = permissions.assignable_pages(current_user)

    requested = {
        key
        for key, granted in normalized.items()
        if granted
    }

    if not requested.issubset(grantable):
        raise PermissionError(
            "Vous ne pouvez pas accorder un accès à une page à laquelle "
            "vous n'avez pas vous-même accès."
        )

    existing_record = fb_auth.get_user(
        target["uid"],
        app=_firebase_app,
    )

    existing_claims = existing_record.custom_claims or {}

    existing_claims["pages"] = normalized

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
        app=_firebase_app,
    )

    invalidate_users_cache()


# ============================================================================
# LISTE DES SOCIÉTÉS
# ============================================================================

def list_companies():
    """
    Retourne les sociétés connues à partir des custom claims utilisateurs.
    """

    companies = {}

    for user in _fetch_all_users_raw():

        company_id = user.get("company_id")
        company_name = user.get("company_name")

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