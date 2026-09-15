# -*- coding: utf-8 -*-
"""
auth/permissions.py — Qui a le droit de faire quoi selon son rôle.

Trois rôles possibles dans user['role'] :
  - 'global_master'   : accès à toutes les sociétés
  - 'company_master'  : administre sa société uniquement
  - 'user'            : utilisateur standard de sa société

Ce module ne contacte jamais Firebase — il ne fait que raisonner sur le
dict utilisateur déjà authentifié (voir auth/authentication.py) et sur
la société actuellement "regardée" (voir components/project_selector.py
pour le cas d'un global_master qui bascule d'une société à l'autre).
"""

GLOBAL_MASTER = "global_master"
COMPANY_MASTER = "company_master"
USER = "user"

ADMIN_ROLES = (GLOBAL_MASTER, COMPANY_MASTER)


def is_global_master(user: dict) -> bool:
    return user["role"] == GLOBAL_MASTER


def is_company_master(user: dict) -> bool:
    return user["role"] == COMPANY_MASTER


def can_administer_users(user: dict) -> bool:
    """Un global_master ou un company_master peut créer/désactiver des
    comptes (le company_master, uniquement dans sa propre société — la
    restriction est appliquée côté auth.authentication.list_users)."""
    return user["role"] in ADMIN_ROLES


def can_switch_company(user: dict) -> bool:
    """Seul un global_master peut changer de société à la volée
    (voir components/project_selector.py)."""
    return is_global_master(user)


def require_role(user: dict, allowed_roles: tuple):
    """Lève une PermissionError si le rôle de l'utilisateur n'est pas
    dans allowed_roles. À utiliser en tête d'un écran d'admin, par
    exemple : permissions.require_role(user, (permissions.GLOBAL_MASTER,))"""
    if user["role"] not in allowed_roles:
        raise PermissionError(f"Rôle '{user['role']}' insuffisant (requis : {allowed_roles}).")

def can_assign_company_master(current_user: dict) -> bool:
    """
    Seul un global_master peut attribuer le rôle company_master.
    """
    return current_user.get("role") == GLOBAL_MASTER

def can_create_user_for(actor: dict, target_role: str, target_company_id: str | None) -> bool:
    """Décide si `actor` a le droit de créer un compte de rôle et de
    société donnés. Reprend la colonne "Créer user" / "Créer company
    master" de la matrice de droits :
      - un global_master peut créer un company_master ou un user, pour
        n'importe quelle société ;
      - un company_master ne peut créer qu'un user, et uniquement dans
        SA propre société ;
      - personne ne peut créer de global_master depuis cette fonction
        (compte réservé, création hors admin).

    À appeler à la fois côté UI (pour construire le formulaire) et côté
    auth.authentication.create_user (pour ne pas dépendre uniquement de
    ce que l'UI a bien voulu afficher — voir list_users() qui applique
    déjà ce principe pour la lecture)."""
    if target_role == GLOBAL_MASTER:
        return False

    if is_global_master(actor):
        return target_role in (COMPANY_MASTER, USER)

    if is_company_master(actor):
        return target_role == USER and target_company_id == actor["company_id"]

    return False


def can_modify_target(actor: dict, target: dict) -> bool:
    """Décide si `actor` a le droit d'agir sur CE compte précis
    (désactiver/réactiver, éditer, modifier ses permissions de pages).
    Centralise les garde-fous anti-escalade qui ne peuvent pas être
    déduits du rôle de l'acteur seul :
      - un compte ne peut pas être modifié par son propre titulaire par
        ce chemin (pas d'auto-désactivation depuis l'admin) ;
      - un global_master ne peut être modifié par personne, pas même un
        autre global_master ;
      - un company_master reste cantonné aux comptes de sa société.

    `target` doit contenir au moins {"uid", "role", "company_id"}."""
    if not can_administer_users(actor):
        return False
    if target["uid"] == actor["uid"]:
        return False
    if target["role"] == GLOBAL_MASTER:
        return False
    if is_company_master(actor) and target["company_id"] != actor["company_id"]:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────
# Permissions par onglet (Réseau / Analyse / Carte / Digital Twin)
# ─────────────────────────────────────────────────────────────────────────
#
# Ce sont les 4 onglets internes de app_pages/analyse.py (st.tabs), pas
# des pages de navigation séparées : il n'y a donc pas d'URL propre à
# chacun. Le contrôle se fait au moment de construire la liste des
# onglets à afficher — voir app_pages/analyse.py.
#
# "twin" (Digital Twin) réutilise le résultat de fréquence calculé par
# l'onglet "analyse" : il n'a donc de sens que si "analyse" est aussi
# autorisé (voir allowed_pages, qui applique cette dépendance).

PAGE_KEYS = ("reseau", "analyse", "carte", "twin")

PAGE_LABELS = {
    "reseau": "Réseau",
    "analyse": "Analyse & Prévision",
    "carte": "Carte Piézométrique",
    "twin": "Digital Twin",
}


def allowed_pages(user: dict) -> set:
    """
    Retourne les pages auxquelles l'utilisateur a accès.

    Règles :
    - un global_master possède toujours tous les accès ;
    - pour les autres rôles, l'absence de claim 'pages' signifie
      aucun accès ;
    - l'absence d'une clé dans 'pages' signifie aucun accès à cette page ;
    - le Digital Twin nécessite obligatoirement l'accès à l'Analyse.
    """

    # ---------------------------------------------------------
    # Exception : global_master
    # ---------------------------------------------------------
    if is_global_master(user):
        return set(PAGE_KEYS)

    # ---------------------------------------------------------
    # Autres rôles : sécurité stricte
    # ---------------------------------------------------------
    raw = user.get("pages") or {}

    allowed = {
        key
        for key in PAGE_KEYS
        if raw.get(key, False)
    }

    # Le Digital Twin dépend de l'Analyse & Prévision.
    if "twin" in allowed and "analyse" not in allowed:
        allowed.discard("twin")

    return allowed

# def allowed_pages(user: dict) -> set:
#     """Ensemble des clés d'onglets auxquels `user` a droit.

#     Absence de la clé "pages" dans les custom claims (compte créé
#     avant l'introduction de cette fonctionnalité, ou jamais configuré)
#     = tout autorisé, pour ne rien casser pour les comptes existants.
#     Dès qu'un admin enregistre une configuration via
#     auth.authentication.set_user_pages, seules les clés explicitement
#     cochées sont autorisées.

#     "twin" est filtré si "analyse" ne l'est pas (dépendance technique,
#     voir plus haut)."""
#     raw = user.get("pages")
#     if raw is None:
#         allowed = set(PAGE_KEYS)
#     else:
#         allowed = {key for key in PAGE_KEYS if raw.get(key, False)}

#     if "twin" in allowed and "analyse" not in allowed:
#         allowed.discard("twin")

#     return allowed


def effective_company_id(user: dict, viewing_company_id: str | None) -> str | None:
    """Détermine la société dont les données doivent être affichées :
    - global_master : celle qu'il a choisie via le sélecteur
      (viewing_company_id), ou None s'il n'a encore rien choisi
      (vue globale / à définir selon le besoin de l'app).
    - company_master / user : toujours la leur, le sélecteur ne
      s'applique pas à eux (viewing_company_id est ignoré)."""
    if is_global_master(user):
        return viewing_company_id
    return user["company_id"]
