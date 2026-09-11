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
        raise PermissionError(
            f"Rôle '{user['role']}' insuffisant (requis : {allowed_roles})."
        )


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
