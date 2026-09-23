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
  - pages (set_user_pages) : ce que le compte peut voir une fois connecté.

Le claim "approved" n'est plus utilisé pour bloquer la connexion.

Cache / ressources :
  - Firebase Admin est initialisé une seule fois via st.cache_resource.
  - L'appel réseau coûteux fb_auth.list_users().iterate_all() est
    mutualisé via st.cache_data(ttl=120).
  - list_users() et list_companies() ne sont pas cachées : leurs règles
    de filtrage/permission sont toujours réévaluées à chaque appel.
  - Toute mutation d'un compte invalide explicitement le cache des
    utilisateurs.
  - authenticate() n'est jamais cachée : elle manipule des mots de passe,
    des tokens et l'état courant du compte.

Session :
  - Les claims (rôle, société, pages) sont copiés dans st.session_state.user
    au login. refresh_session_user() permet de les relire depuis Firebase
    en cours de session (appelée, avec un throttle, par apps_streamlit.py),
    afin qu'un changement de droits ou une désactivation soit pris en
    compte sans attendre une reconnexion.
"""

import requests
import streamlit as st
import firebase_admin
from firebase_admin import auth as fb_auth
from firebase_admin import credentials

from piezo_app.auth import permissions


# ============================================================================
# INITIALISATION FIREBASE
# ============================================================================

@st.cache_resource
def _init_firebase():
    """
    Initialise Firebase Admin une seule fois par processus Streamlit.

    st.cache_resource est utilisé car l'application Firebase est une
    ressource partagée et réutilisable, et non une donnée à recalculer.
    """

    if firebase_admin._apps:
        return firebase_admin.get_app()

    cred_dict = dict(st.secrets["firebase_service_account"])
    cred = credentials.Certificate(cred_dict)

    return firebase_admin.initialize_app(cred)


_init_firebase()


# ============================================================================
# CONFIGURATION FIREBASE AUTHENTICATION
# ============================================================================

_API_KEY = st.secrets["firebase"]["api_key"]

_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/"
    f"accounts:signInWithPassword?key={_API_KEY}"
)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class EmailNotVerifiedError(Exception):
    """
    Conservée pour compatibilité éventuelle.

    La vérification email n'est plus effectuée dans authenticate().
    Elle est gérée en amont, au moment de l'inscription / du clic sur
    le lien de confirmation.
    """

    pass


class PendingApprovalError(Exception):
    """
    Conservée pour compatibilité éventuelle.

    authenticate() ne la lève plus : un compte désactivé ou sans rôle
    attribué retourne simplement None.
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
    Authentifie un utilisateur auprès de Firebase.

    Le compte doit :
        - exister ;
        - ne pas être désactivé ;
        - posséder un rôle.

    Retourne None si l'authentification échoue.

    IMPORTANT :
    Cette fonction ne doit jamais être mise en cache.
    """

    try:
        response = requests.post(
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

    # ------------------------------------------------------------------------
    # Authentification Firebase échouée
    # ------------------------------------------------------------------------

    if response.status_code != 200:
        return None

    try:
        data = response.json()

        id_token = data["idToken"]
        uid = data["localId"]

    except (ValueError, KeyError):
        return None

    # ------------------------------------------------------------------------
    # Vérification du token
    # ------------------------------------------------------------------------

    try:
        decoded_token = fb_auth.verify_id_token(id_token)

    except Exception:
        return None

    if decoded_token.get("uid") != uid:
        return None

    # ------------------------------------------------------------------------
    # Récupération du compte Firebase
    # ------------------------------------------------------------------------

    try:
        user_record = fb_auth.get_user(uid)

    except Exception:
        return None

    # ------------------------------------------------------------------------
    # Compte désactivé
    # ------------------------------------------------------------------------

    if user_record.disabled:
        return None

    # ------------------------------------------------------------------------
    # Custom claims
    # ------------------------------------------------------------------------

    claims = decoded_token
    role = claims.get("role")

    if role is None:
        return None

    # ------------------------------------------------------------------------
    # Profil utilisateur
    # ------------------------------------------------------------------------

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


# ============================================================================
# RAFRAÎCHISSEMENT DE LA SESSION
# ============================================================================

def refresh_session_user(user: dict) -> dict | None:
    """
    Relit rôle, société et pages depuis Firebase pour un utilisateur déjà
    connecté, sans redemander le mot de passe.

    Retourne :
        - un dict utilisateur à jour (mêmes clés que authenticate()) ;
        - None si le compte n'existe plus, est désactivé ou n'a plus de
          rôle : l'appelant doit alors déconnecter l'utilisateur.

    En cas d'erreur réseau ou Firebase transitoire, la session existante
    est conservée telle quelle (on ne déconnecte pas quelqu'un à cause
    d'un incident réseau passager).

    IMPORTANT :
    Cette fonction ne doit jamais être mise en cache.
    """

    try:
        record = fb_auth.get_user(user["uid"])

    except fb_auth.UserNotFoundError:
        return None

    except Exception:
        return user

    claims = record.custom_claims or {}

    if record.disabled or claims.get("role") is None:
        return None

    return {
        **user,
        "email": record.email,
        "role": claims["role"],
        "company_id": claims.get("company_id"),
        "company_name": claims.get("company_name"),
        "pages": claims.get("pages"),
    }


# ============================================================================
# CACHE DES UTILISATEURS FIREBASE
# ============================================================================

@st.cache_data(ttl=120)
def _fetch_all_users_raw():
    """
    Récupère tous les comptes Firebase.

    Cette fonction constitue le seul point de cache du listing Firebase.

    Le résultat est volontairement brut :
        - aucune permission ;
        - aucun filtrage par société ;
        - aucune décision d'accès.

    Le filtrage est effectué ensuite par list_users(), à chaque appel.

    TTL :
        120 secondes.

    Toute mutation de compte appelle :
        _fetch_all_users_raw.clear()
    """

    result = []

    for user in fb_auth.list_users().iterate_all():
        claims = user.custom_claims or {}

        result.append(
            {
                "uid": user.uid,
                "email": user.email,
                "role": claims.get("role"),
                "company_id": claims.get("company_id"),
                "company_name": claims.get("company_name"),
                "disabled": user.disabled,
                "pages": claims.get("pages"),
            }
        )

    return result


def invalidate_users_cache():
    """
    Invalide le cache du listing Firebase.

    À appeler après toute écriture de claims ou toute création /
    suppression de compte faite hors de ce module (ex. auth/registration.py).
    """

    _fetch_all_users_raw.clear()


# ============================================================================
# LISTE DES UTILISATEURS
# ============================================================================

def list_users(current_user: dict):
    """
    Retourne les utilisateurs visibles par l'utilisateur courant.

    Le résultat Firebase provient du cache _fetch_all_users_raw().

    Le filtrage n'est PAS caché afin que les permissions soient
    systématiquement réévaluées.
    """

    role = current_user.get("role")

    if role not in permissions.ADMIN_ROLES:
        raise PermissionError(
            "Droits insuffisants pour lister les utilisateurs."
        )

    result = [
        user
        for user in _fetch_all_users_raw()
        if user["role"] is not None
    ]

    if role == permissions.COMPANY_MASTER:
        company_id = current_user.get("company_id")

        result = [
            user
            for user in result
            if user["company_id"] == company_id
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

    if role == permissions.GLOBAL_MASTER and company_id is not None:
        raise ValueError(
            "Un global_master ne doit pas être rattaché à une société."
        )

    if (
        role in (permissions.COMPANY_MASTER, permissions.USER)
        and company_id is None
    ):
        raise ValueError(
            "company_id est obligatoire pour ce rôle."
        )

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

    try:
        fb_auth.set_custom_user_claims(
            user_record.uid,
            claims,
        )

    except Exception:
        # Sans rôle, le compte serait invisible dans l'admin (voir
        # list_users) tout en bloquant l'adresse email : on le supprime
        # pour ne pas laisser de compte orphelin.
        try:
            fb_auth.delete_user(user_record.uid)
        except Exception:
            pass
        raise

    # Le listing Firebase est désormais périmé.
    _fetch_all_users_raw.clear()

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
    )

    # Le listing Firebase est désormais périmé.
    _fetch_all_users_raw.clear()


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
    Modifie le rôle d'un compte existant et éventuellement sa société.
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
            "Le rôle global_master ne peut pas être attribué depuis cet écran."
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
        new_role in (permissions.COMPANY_MASTER, permissions.USER)
        and target_company_id is None
    ):
        raise ValueError(
            "company_id est obligatoire pour ce rôle."
        )

    existing_claims = (
        fb_auth.get_user(target["uid"]).custom_claims or {}
    )

    existing_claims["role"] = new_role
    existing_claims["company_id"] = target_company_id
    existing_claims["company_name"] = target_company_name

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
    )

    # Les données utilisateur en cache sont périmées.
    _fetch_all_users_raw.clear()


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

    Un company_master ne peut accorder à ses users que les pages
    auxquelles il a lui-même accès.

    Les pages sont normalisées avant écriture (permissions.normalize_pages) :
    toutes les PAGE_KEYS sont écrites, et "twin" / "interpretation" sont
    forcées à False si "analyse" n'est pas accordée. Ce qui est stocké
    dans Firebase correspond donc exactement à ce qui sera effectif.
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

    existing_claims = (
        fb_auth.get_user(target["uid"]).custom_claims or {}
    )

    existing_claims["pages"] = normalized

    fb_auth.set_custom_user_claims(
        target["uid"],
        existing_claims,
    )

    # Les données utilisateur en cache sont périmées.
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

    # Société cible : celle fournie, sinon celle déjà en place sur le compte.
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

# ============================================================================
# LISTE DES SOCIÉTÉS
# ============================================================================

def list_companies():
    """
    Retourne la liste des sociétés connues.

    Réutilise le cache _fetch_all_users_raw().

    Aucun cache supplémentaire n'est appliqué : la transformation est
    locale et très légère, tandis que le cache principal mutualise déjà
    l'appel réseau Firebase.
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
