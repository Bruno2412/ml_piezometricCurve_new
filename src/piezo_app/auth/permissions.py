# -*- coding: utf-8 -*-
"""
auth/permissions.py — Qui a le droit de faire quoi selon son rôle.

Quatre rôles possibles dans user['role'] :
  - 'super_master'    : accès total, y compris rétrograder un global_master
  - 'global_master'   : accès à toutes les sociétés
  - 'company_master'  : administre sa société uniquement
  - 'user'            : utilisateur standard de sa société

Ce module ne contacte jamais Firebase — il ne fait que raisonner sur le
dict utilisateur déjà authentifié (voir auth/authentication.py) et sur
la société actuellement "regardée" (voir components/project_selector.py
pour le cas d'un super_master/global_master qui bascule d'une société à
l'autre).
"""

SUPER_MASTER = "super_master"
GLOBAL_MASTER = "global_master"
COMPANY_MASTER = "company_master"
USER = "user"

ADMIN_ROLES = (SUPER_MASTER, GLOBAL_MASTER, COMPANY_MASTER)


# ─────────────────────────────────────────────────────────────────────────
# Permissions par onglet
# ─────────────────────────────────────────────────────────────────────────
#
# Ce sont les 5 onglets métier de app_pages/analyse.py (st.tabs), pas
# des pages de navigation séparées : il n'y a donc pas d'URL propre à
# chacun. Le contrôle se fait au moment de construire la liste des
# onglets à afficher — voir app_pages/analyse.py.
#
# L'ORDRE de PAGE_KEYS est aussi l'ordre d'affichage et d'exécution des
# onglets : "analyse" doit précéder "twin" et "interpretation", car ces
# deux onglets réutilisent le résultat de fréquence (freq) calculé par
# l'onglet "analyse".

PAGE_KEYS = ("chroniques", "analyse", "carte", "twin", "interpretation")

PAGE_LABELS = {
    "chroniques": "Chroniques",
    "analyse": "Analyse & Prévision",
    "carte": "Carte Piézométrique",
    "twin": "Digital Twin",
    "interpretation": "Interprétation",
}

# Onglets qui n'ont de sens que si "analyse" est aussi autorisé.
DEPENDS_ON_ANALYSE = ("twin", "interpretation")


# ─────────────────────────────────────────────────────────────────────────
# Rôles
# ─────────────────────────────────────────────────────────────────────────
def is_super_master(user: dict) -> bool:
    return user.get("role") == SUPER_MASTER


def is_global_master(user: dict) -> bool:
    return user.get("role") == GLOBAL_MASTER


def is_company_master(user: dict) -> bool:
    return user.get("role") == COMPANY_MASTER


def has_transverse_access(user: dict) -> bool:
    """True si l'utilisateur voit/gère les données de toutes les sociétés
    sans restriction (super_master, global_master)."""
    return user.get("role") in (SUPER_MASTER, GLOBAL_MASTER)


def can_administer_users(user: dict) -> bool:
    """Un super_master, un global_master ou un company_master peut
    créer/désactiver des comptes (le company_master, uniquement dans sa
    propre société — la restriction est appliquée côté
    auth.authentication.list_users)."""
    return user.get("role") in ADMIN_ROLES


def can_switch_company(user: dict) -> bool:
    """Un super_master ou un global_master peuvent changer de société à
    la volée."""
    return has_transverse_access(user)


def require_role(user: dict, allowed_roles: tuple):
    """Lève une PermissionError si le rôle de l'utilisateur n'est pas
    dans allowed_roles. À utiliser en tête d'un écran d'admin, par
    exemple : permissions.require_role(user, (permissions.GLOBAL_MASTER,))"""
    if user.get("role") not in allowed_roles:
        raise PermissionError(
            f"Rôle '{user.get('role')}' insuffisant (requis : {allowed_roles})."
        )


def can_assign_company_master(current_user: dict) -> bool:
    """Un super_master ou un global_master peuvent attribuer le rôle
    company_master."""
    return has_transverse_access(current_user)


def can_create_user_for(actor: dict, target_role: str, target_company_id: str | None) -> bool:
    """Décide si `actor` a le droit de créer un compte de rôle et de
    société donnés.
      - un super_master peut créer n'importe quel rôle (sauf un autre
        super_master), pour n'importe quelle société ;
      - un global_master peut créer un company_master ou un user, pour
        n'importe quelle société ;
      - un company_master ne peut créer qu'un user, et uniquement dans
        SA propre société ;
      - personne ne peut créer de super_master depuis cette fonction
        (compte réservé, création hors admin)."""
    if is_super_master(actor):
        return target_role != SUPER_MASTER

    if target_role in (GLOBAL_MASTER, SUPER_MASTER):
        return False

    if is_global_master(actor):
        return target_role in (COMPANY_MASTER, USER)

    if is_company_master(actor):
        return (
            target_role == USER
            and target_company_id is not None
            and target_company_id == actor.get("company_id")
        )

    return False


def can_modify_target(actor: dict, target: dict) -> bool:
    """Décide si `actor` a le droit d'agir sur CE compte précis
    (désactiver/réactiver, éditer, modifier ses permissions de pages,
    changer son rôle). Centralise les garde-fous anti-escalade :
      - un compte ne peut pas être modifié par son propre titulaire par
        ce chemin (pas d'auto-désactivation depuis l'admin) ;
      - un super_master ne peut être modifié par personne, pas même un
        autre super_master ;
      - un global_master ne peut être modifié que par un super_master
        (c'est ce qui permet la rétrogradation global_master ->
        company_master, exclusivement réservée au super_master) ;
      - un company_master reste cantonné aux comptes de sa société.

    `target` doit contenir au moins {"uid", "role", "company_id"}."""
    if not can_administer_users(actor):
        return False
    if target.get("uid") == actor.get("uid"):
        return False
    if target.get("role") == SUPER_MASTER:
        return False
    if target.get("role") == GLOBAL_MASTER and not is_super_master(actor):
        return False
    if is_company_master(actor) and target.get("company_id") != actor.get("company_id"):
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────
# Pages (onglets)
# ─────────────────────────────────────────────────────────────────────────

def _as_pages_dict(raw) -> dict:
    """Accepte le claim 'pages' sous forme de dict {clé: bool} ou de
    liste/tuple/set de clés autorisées ; tout le reste vaut « aucun accès »."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (list, tuple, set)):
        return {str(key): True for key in raw}
    return {}


def normalize_pages(pages) -> dict:
    """
    Retourne un dict complet {clé: bool} pour toutes les PAGE_KEYS, en
    appliquant la règle de dépendance : sans "analyse", les onglets de
    DEPENDS_ON_ANALYSE sont forcément à False.

    Utilisée à la fois à la lecture (allowed_pages) et à l'écriture
    (auth.authentication.set_user_pages), pour que ce qui est stocké
    dans Firebase soit exactement ce qui est effectif.
    """
    raw = _as_pages_dict(pages)
    result = {key: bool(raw.get(key, False)) for key in PAGE_KEYS}

    if not result["analyse"]:
        for key in DEPENDS_ON_ANALYSE:
            result[key] = False

    return result


def allowed_pages(user: dict) -> set:
    """
    Retourne les pages auxquelles l'utilisateur a accès.

    Règles :
    - un super_master ou un global_master possède toujours tous les
      accès ;
    - pour les autres rôles, l'absence de claim 'pages' signifie
      aucun accès ;
    - l'absence d'une clé dans 'pages' signifie aucun accès à cette page
      (un compte enregistré avant l'ajout d'un onglet ne le voit donc
      qu'après une nouvelle sauvegarde de ses droits par l'admin) ;
    - "twin" et "interpretation" nécessitent obligatoirement "analyse".
    """
    if has_transverse_access(user):
        return set(PAGE_KEYS)

    normalized = normalize_pages(user.get("pages"))
    return {key for key, granted in normalized.items() if granted}


def assignable_pages(actor: dict) -> set:
    """
    Pages qu'un acteur a le droit d'accorder à un compte qu'il
    administre (via set_user_pages).

    Principe : on ne peut pas déléguer plus de droits qu'on n'en
    possède soi-même.
      - un super_master ou un global_master peut accorder n'importe
        quelle page à n'importe qui ;
      - un company_master ne peut accorder que les pages auxquelles
        IL a lui-même accès (voir allowed_pages) — il peut ainsi
        gérer les onglets de ses users, mais seulement dans la limite
        de ses propres droits.
    """
    if has_transverse_access(actor):
        return set(PAGE_KEYS)
    return allowed_pages(actor)


# ─────────────────────────────────────────────────────────────────────────
# Société affichée
# ─────────────────────────────────────────────────────────────────────────

def effective_company_id(user: dict, viewing_company_id: str | None) -> str | None:
    """Détermine la société dont les données doivent être affichées :
    - super_master / global_master : celle qu'il a choisie via le
      sélecteur (viewing_company_id), ou None s'il n'a encore rien
      choisi (vue globale / à définir selon le besoin de l'app).
    - company_master / user : toujours la leur, le sélecteur ne
      s'applique pas à eux (viewing_company_id est ignoré)."""
    if has_transverse_access(user):
        return viewing_company_id
    return user.get("company_id")