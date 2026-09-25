# -*- coding: utf-8 -*-
"""Persistance et contexte des projets dans Firestore.

Le projet est le contexte racine de l'application : aucune donnée métier
(chroniques, cartographie, analyse, Digital Twin...) ne doit être utilisée
sans projet courant.

La couche utilise le SDK Firebase Admin. Les règles Firestore ne sont pas
utilisées comme mécanisme d'autorisation ici : l'application serveur utilise
le SDK Admin, qui contourne les règles Firestore. Les droits sont donc
réévalués dans ce module avant chaque lecture/écriture de projet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import streamlit as st
from firebase_admin import firestore

from piezo_app.auth import authentication 

COLLECTION_NAME = "Projects"

# Clés alimentées par les pages métier (widgets Streamlit + données
# dérivées) : elles ne doivent jamais survivre à un changement de projet,
# sous peine d'afficher les données ou paramètres d'un autre projet sous
# le nom du projet nouvellement ouvert.
_PROJECT_SCOPED_KEYS = (
    "data_ready",
    "shared_map_data",
    "analysis_raw",
    "upl_files",
    "model_name",
    "future_years",
    "validation_years",
    "ci_pct",
    "n_bootstraps",
    "thickness",
    "Q",
    "S",
    "Area",
    "distance",
    "K",
    "selection",
    "target_name",
    "share_with_cartography",
    "parsed_chroniques",
)


def _purge_project_scoped_state() -> None:
    """Retire du session_state tout ce qui appartient au projet quitté."""
    for key in _PROJECT_SCOPED_KEYS:
        st.session_state.pop(key, None)


class ProjectNotFoundError(Exception):
    """Projet inexistant ou inaccessible pour l'utilisateur courant."""


class ProjectValidationError(ValueError):
    """Données insuffisantes ou incohérentes pour créer un projet."""


def _db():
    """Retourne le client Firestore déjà initialisé par Firebase Admin."""
    return firestore.client()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_project(doc) -> dict[str, Any]:
    data = doc.to_dict() or {}
    return {
        "id": doc.id,
        "projectName": str(data.get("projectName", "")).strip(),
        "projectDescription": str(data.get("projectDescription", "")).strip(),
        "projectOwner": data.get("projectOwner"),
        "projectShare": bool(data.get("projectShare", False)),
        "companyId": data.get("companyId"),
        "companyName": data.get("companyName", ""),
        "createdAt": data.get("createdAt"),
        "updatedAt": data.get("updatedAt"),
    }


def _is_allowed(project: dict[str, Any], user: dict[str, Any]) -> bool:
    """Vérifie l'accès métier à un projet.

    - global_master : accès transverse à tous les projets ;
    - propriétaire : accès à son propre projet ;
    - même société + projectShare=True : accès partagé ;
    - sinon : aucun accès.
    """
    if user.get("role") == "global_master":
        return True

    uid = user.get("uid")
    company_id = user.get("company_id")

    if uid and project.get("projectOwner") == uid:
        return True

    return bool(
        project.get("projectShare")
        and company_id
        and project.get("companyId") == company_id
    )


def list_projects(user: dict[str, Any]) -> list[dict[str, Any]]:
    """Retourne les projets accessibles à l'utilisateur courant.

    Les requêtes sont volontairement simples (égalité sur owner/company)
    afin d'éviter une requête OR complexe et de limiter les index requis.
    Les résultats sont dédoublonnés puis filtrés une seconde fois côté Python.
    """
    if not user or not user.get("uid"):
        return []

    collection = _db().collection(COLLECTION_NAME)
    docs = {}

    if user.get("role") == "global_master":
        for doc in collection.stream():
            docs[doc.id] = doc
    else:
        for doc in collection.where("projectOwner", "==", user["uid"]).stream():
            docs[doc.id] = doc

        company_id = user.get("company_id")
        if company_id:
            # Un seul filtre Firestore : pas de dépendance à un index
            # composite pour la première version. Le partage est vérifié
            # ensuite par _is_allowed().
            query = collection.where("companyId", "==", company_id)
            for doc in query.stream():
                docs[doc.id] = doc

    projects = [
        _normalize_project(doc)
        for doc in docs.values()
    ]
    projects = [project for project in projects if _is_allowed(project, user)]

    projects.sort(
        key=lambda p: (
            p.get("projectName", "").lower(),
            p.get("id", ""),
        )
    )
    return projects


def get_project(project_id: str, user: dict[str, Any]) -> dict[str, Any] | None:
    """Charge un projet et vérifie immédiatement les droits d'accès."""
    if not project_id or not user or not user.get("uid"):
        return None

    doc = _db().collection(COLLECTION_NAME).document(project_id).get()
    if not doc.exists:
        return None

    project = _normalize_project(doc)
    if not _is_allowed(project, user):
        return None

    return project


def create_project(
    user: dict[str, Any],
    *,
    name: str,
    description: str = "",
    company_id: str | None = None,
    company_name: str | None = None,
    share_with_company: bool = False,
) -> dict[str, Any]:
    """Crée un projet vide et retourne ses métadonnées.

    Aucun fichier ni aucune chronique n'est enregistré à ce stade.
    """
    if not user or not user.get("uid"):
        raise ProjectValidationError("Utilisateur non authentifié.")

    name = name.strip()
    description = description.strip()

    if not name:
        raise ProjectValidationError("Le nom du projet est obligatoire.")

    if len(name) > 150:
        raise ProjectValidationError("Le nom du projet ne peut pas dépasser 150 caractères.")

    if len(description) > 2000:
        raise ProjectValidationError(
            "La description ne peut pas dépasser 2000 caractères."
        )

    if user.get("role") != "global_master":
        company_id = user.get("company_id")
        company_name = user.get("company_name") or ""

    company_id = (company_id or "").strip()
    company_name = (company_name or "").strip()

    if not company_id:
        raise ProjectValidationError("Une société doit être associée au projet.")

    # Un projet partagé n'a de sens que dans une société identifiée.
    if share_with_company and not company_id:
        raise ProjectValidationError(
            "Impossible de partager le projet sans société associée."
        )

    collection = _db().collection(COLLECTION_NAME)
    doc_ref = collection.document()
    now = _now_iso()

    payload = {
        "projectName": name,
        "projectDescription": description,
        "projectOwner": user["uid"],
        "projectShare": bool(share_with_company),
        "companyId": company_id,
        "companyName": company_name,
        "createdAt": now,
        "updatedAt": now,
    }

    doc_ref.set(payload)
    return _normalize_project(doc_ref.get())


def set_current_project(project_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Sélectionne un projet après avoir revérifié les droits."""
    project = get_project(project_id, user)
    if project is None:
        raise ProjectNotFoundError("Projet inexistant ou accès refusé.")

    if st.session_state.get("current_project_id") != project["id"]:
        # Vrai changement de projet (pas un simple rafraîchissement du
        # projet déjà ouvert) : tout ce qui a été chargé/saisi pour l'ancien
        # projet devient invalide et ne doit pas fuiter vers le nouveau.
        _purge_project_scoped_state()

    st.session_state["current_project_id"] = project["id"]
    st.session_state["current_project"] = project
    return project


def clear_current_project() -> None:
    """Ferme le projet courant sans toucher aux données Firestore."""
    st.session_state.pop("current_project_id", None)
    st.session_state.pop("current_project", None)
    _purge_project_scoped_state()


def current_project(user: dict[str, Any]) -> dict[str, Any] | None:
    """Retourne le projet courant s'il existe encore et reste accessible."""
    project_id = st.session_state.get("current_project_id")
    if not project_id:
        return None

    cached = st.session_state.get("current_project")
    if isinstance(cached, dict) and cached.get("id") == project_id:
        # Le contrôle d'accès est refait par get_project : le cache n'est
        # jamais considéré comme une preuve d'autorisation.
        project = get_project(project_id, user)
        if project is not None:
            st.session_state["current_project"] = project
            return project

    project = get_project(project_id, user)
    if project is None:
        clear_current_project()
        return None

    st.session_state["current_project"] = project
    return project


def require_current_project(user: dict[str, Any]) -> dict[str, Any]:
    """Bloque une page métier si aucun projet accessible n'est ouvert."""
    project = current_project(user)
    if project is None:
        st.warning(
            "Aucun projet n'est ouvert. Créez ou sélectionnez un projet "
            "avant d'accéder aux données piézométriques."
        )
        st.stop()
    return project
