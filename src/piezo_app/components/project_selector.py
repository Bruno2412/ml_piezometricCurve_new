# -*- coding: utf-8 -*-
"""Sélecteur du projet courant.

Le projet est le contexte racine des données métier de l'application.
Ce composant affiche les projets auxquels l'utilisateur connecté a accès
et permet d'ouvrir/fermer le projet courant depuis la sidebar.
"""

import streamlit as st

from piezo_app.services import projects


def render() -> None:
    """Affiche le projet courant et permet d'en changer."""
    user = st.session_state.get("user")
    if not user:
        return

    available = projects.list_projects(user)
    current = projects.current_project(user)

    st.sidebar.divider()
    st.sidebar.caption("Projet courant")

    if not available:
        st.sidebar.info("Aucun projet disponible.")
        if current is not None:
            projects.clear_current_project()
        return

    ids = [project["id"] for project in available]
    labels = {
        project["id"]: project["projectName"] or project["id"]
        for project in available
    }

    current_id = current["id"] if current else None
    selected = st.sidebar.selectbox(
        "Projet",
        options=ids,
        format_func=lambda project_id: labels[project_id],
        index=ids.index(current_id) if current_id in ids else 0,
        key="current_project_selector",
    )

    if selected != current_id:
        projects.set_current_project(selected, user)
        st.rerun()

    current = projects.current_project(user)
    if current:
        if current.get("projectShare"):
            st.sidebar.caption("🔗 Partagé avec la société")
        else:
            st.sidebar.caption("🔒 Projet privé")

        if st.sidebar.button("Fermer le projet", use_container_width=True):
            projects.clear_current_project()
            st.rerun()
