# -*- coding: utf-8 -*-
"""
auth/authentication.py — Connexion à Firebase Authentication et gestion
des comptes.

Rôles :
  - global_master   : voit toutes les sociétés
  - company_master  : administre une société
  - user            : utilisateur standard

L'activation d'un compte repose sur deux leviers indépendants,
appliqués séparément par l'administrateur dans tab_global_overview.py :
  - disabled (set_user_active) : le compte peut se connecter ou non ;
  - pages (set_user_pages) : ce que le compte peut voir une fois
    connecté.

Le claim "approved" n'est plus utilisé pour bloquer la connexion.

Cache :
  - L'appel réseau Firebase le plus coûteux (`fb_auth.list_users().iterate_all()`)
    est mutualisé et caché via `_fetch_all_users_raw()` (st.cache_data).
    `list_users()` et `list_companies()` consomment ce cache et appliquent
    leur propre logique de filtrage/permission à chaque appel (non caché,
    pour ne jamais figer une décision de droits d'accès).
  - Toute mutation (create_user, set_user_active, set_user_pages) invalide
    ce cache via `_fetch_all_users_raw.clear()` pour éviter d'afficher des
    données périmées.
  - `authenticate()` n'est jamais caché (sécurité : mots de passe, tokens).
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

    cred_dict = dict(st.secrets["firebase_service_account"])

    cred = credentials.Certificate(cred_dict)

    return firebase_admin.initialize_app(cred)


_init_firebase()


_API_KEY = st.secrets["firebase"]["api_key"]

_SIGN_IN_URL = (
    f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={_API_KEY}"
)


class EmailNotVerifiedError(Exception):
    """
    Conservée pour compatibilité éventuelle.
    La vérification email n'est plus vérifiée dans authenticate()
    (elle est gérée en amont, au moment de l'inscription/du clic sur
    le lien de confirmation — voir auth/registration.py et
    app_streamlit.py).
    """

    pass


class PendingApprovalError(Exception):
    """
    Conservée pour compatibilité éventuelle (ex. import ailleurs dans
    l'application). authenticate() ne la lève plus : un compte
    désactivé ou sans rôle attribué fait simplement retourner None,
    au même titre qu'un échec d'authentification classique.
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
        - posséder un rôle.

    Retourne None si l'authentification échoue, y compris si le compte
    est désactivé ou n'a pas encore de rôle attribué (compte en attente
    de validation par un administrateur).

    NE JAMAIS mettre cette fonction en cache : elle manipule un mot de
    passe en clair et génère des tokens de session à chaque appel.
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
        decoded_token = fb_auth.verify_id_token(id_token)

    except Exception:
        return None

    if decoded_token.get("uid") != uid:
        return None

    # ---------------------------------------------------------
    # Récupération du compte Firebase
    # ---------------------------------------------------------

    try:
        user_record = fb_auth.get_user(uid)

    except Exception:
        return None

    # ---------------------------------------------------------
    # Compte désactivé
    # ---------------------------------------------------------

    if user_record.disabled:
        return None

    # ---------------------------------------------------------
    # Custom claims
    # ---------------------------------------------------------

    claims = decoded_token

    role = claims.get("role")

    if role is None:
        return None

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
    """

    if role == "company_master" and not permissions.can_assign_company_master(current_user):
        raise PermissionError("Seul un global_master peut attribuer le rôle company_master.")

    if not permissions.can_create_user_for(
        current_user,
        role,
        company_id,
    ):
        raise PermissionError(
            f"Le rôle '{current_user['role']}' ne peut pas créer "
            f"un compte '{role}'" + (f" pour la société '{company_id}'." if company_id else ".")
        )

    if role == "global_master" and company_id is not None:
        raise ValueError("Un global_master ne doit pas être rattaché à une société.")

    if (
        role
        in (
            "company_master",
            "user",
        )
        and company_id is None
    ):
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

    # Le cache des comptes est désormais périmé : on l'invalide.
    _fetch_all_users_raw.clear()

    return user_record.uid


@st.cache_data(ttl=300)
def _fetch_all_users_raw():
    """
    Appel réseau Firebase brut et coûteux (liste tous les comptes).
    Mis en cache 5 minutes. Ne fait aucun filtrage par permission :
    c'est aux fonctions appelantes (list_users, list_companies) de
    filtrer selon le rôle de l'utilisateur courant, à chaque appel,
    pour ne jamais figer une décision de droits d'accès dans le cache.

    Invalidé explicitement par toute mutation de compte
    (create_user, set_user_active, set_user_pages) via
    `_fetch_all_users_raw.clear()`.
    """

    result = []

    for u in fb_auth.list_users().iterate_all():
        claims = u.custom_claims or {}

        result.append(
            {
                "uid": u.uid,
                "email": u.email,
                "role": claims.get("role"),
                "company_id": claims.get("company_id"),
                "company_name": claims.get("company_name"),
                "disabled": u.disabled,
                "pages": claims.get("pages"),
            }
        )

    return result


def list_users(
    current_user: dict,
):
    """
    Utilisateurs visibles selon le rôle de l'appelant.

    S'appuie sur le cache `_fetch_all_users_raw()` pour l'appel réseau ;
    le filtrage par rôle/société est réévalué à chaque appel (non caché).
    """

    if current_user["role"] not in (
        "global_master",
        "company_master",
    ):
        raise PermissionError("Droits insuffisants pour lister les utilisateurs.")

    result = [u for u in _fetch_all_users_raw() if u["role"] is not None]

    if current_user["role"] == "company_master":
        result = [u for u in result if u["company_id"] == current_user["company_id"]]

    return result


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
        raise PermissionError("Droits insuffisants pour modifier ce compte.")

    fb_auth.update_user(
        target["uid"],
        disabled=not is_active,
    )

    # Le cache des comptes est désormais périmé : on l'invalide.
    _fetch_all_users_raw.clear()


def set_user_role(                                                    
    current_user: dict,
    target: dict,
    new_role: str,
    new_company_id: str | None = None,
    new_company_name: str | None = None,
):
    """
    Modifie le rôle d'un compte existant, et éventuellement sa société
    (ex. promouvoir un 'user' en 'company_master', avec ou sans
    changement de société).

    Si new_company_id/new_company_name ne sont pas fournis, la société
    actuelle du compte est conservée.
    """

    if not permissions.can_modify_target(current_user, target):
        raise PermissionError("Droits insuffisants pour modifier ce compte.")

    if new_role == "global_master":
        raise PermissionError("Le rôle global_master ne peut pas être attribué depuis cet écran.")

    if new_role == "company_master" and not permissions.can_assign_company_master(current_user):
        raise PermissionError("Seul un global_master peut attribuer le rôle company_master.")

    target_company_id = new_company_id if new_company_id is not None else target.get("company_id")
    target_company_name = (
        new_company_name if new_company_name is not None else target.get("company_name")
    )

    if not permissions.can_create_user_for(current_user, new_role, target_company_id):
        raise PermissionError(
            f"Le rôle '{current_user['role']}' ne peut pas attribuer "
            f"le rôle '{new_role}' à cette société."
        )

    if new_role in ("company_master", "user") and target_company_id is None:
        raise ValueError("company_id est obligatoire pour ce rôle.")

    existing_claims = fb_auth.get_user(target["uid"]).custom_claims or {}

    existing_claims["role"] = new_role
    existing_claims["company_id"] = target_company_id
    existing_claims["company_name"] = target_company_name

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
    )

    # Le cache des comptes est désormais périmé : on l'invalide.
    _fetch_all_users_raw.clear()


def set_user_pages(
    current_user: dict,
    target: dict,
    pages: dict,
):
    """
    Définit les pages accessibles à un utilisateur.

    Un company_master ne peut accorder à ses users que les pages
    auxquelles il a lui-même accès (voir permissions.assignable_pages).
    """

    if not permissions.can_modify_target(
        current_user,
        target,
    ):
        raise PermissionError("Droits insuffisants pour modifier les pages de ce compte.")

    grantable = permissions.assignable_pages(current_user)

    requested = {key for key in permissions.PAGE_KEYS if pages.get(key, False)}

    if not requested.issubset(grantable):
        raise PermissionError(
            "Vous ne pouvez pas accorder un accès à une page à laquelle "
            "vous n'avez pas vous-même accès."
        )

    existing_claims = fb_auth.get_user(target["uid"]).custom_claims or {}

    existing_claims["pages"] = {key: bool(pages.get(key, False)) for key in permissions.PAGE_KEYS}

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
    )

    _fetch_all_users_raw.clear()


def list_companies():
    """
    Retourne la liste des sociétés connues.

    Réutilise le cache `_fetch_all_users_raw()` au lieu de refaire un
    appel Firebase séparé (évite un doublon avec list_users).
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
