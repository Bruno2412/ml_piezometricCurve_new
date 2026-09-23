# -*- coding: utf-8 -*-
"""Page d'accueil des projets.

Un projet doit être créé ou sélectionné avant toute donnée métier.
Cette page ne charge aucune chronique et ne lance aucune analyse.
"""

import streamlit as st

from piezo_app.auth import authentication, permissions
from piezo_app.services import projects


user = st.session_state.get("user")
if user is None:
    st.error("Connexion requise.")
    st.stop()

st.title("📁 Mes projets")
st.caption(
    "Un projet constitue le contexte de travail. Les chroniques, la cartographie, "
    "les analyses et le Digital Twin seront rattachés au projet sélectionné."
)

current = projects.current_project(user)

if current:
    st.success(f"Projet ouvert : **{current['projectName']}**")
    if current.get("projectDescription"):
        st.write(current["projectDescription"])

    if st.button("Fermer le projet", key="close_project_page"):
        projects.clear_current_project()
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Création d'un projet vide
# ---------------------------------------------------------------------------

st.subheader("Créer un projet")

if permissions.is_global_master(user):
    try:
        all_users = authentication.list_users(user)
    except PermissionError:
        all_users = []

    companies = {}
    for account in all_users:
        if account.get("company_id"):
            companies[account["company_id"]] = account.get("company_name") or account["company_id"]

    company_options = list(companies)
    if company_options:
        selected_company = st.selectbox(
            "Société du projet",
            company_options,
            format_func=lambda cid: companies[cid],
            key="new_project_company",
        )
        project_company_id = selected_company
        project_company_name = companies[selected_company]
    else:
        project_company_id = ""
        project_company_name = ""
        st.warning("Aucune société n'est actuellement disponible.")
else:
    project_company_id = user.get("company_id") or ""
    project_company_name = user.get("company_name") or project_company_id
    st.text_input(
        "Société",
        value=project_company_name,
        disabled=True,
    )

with st.form("create_project_form", clear_on_submit=True):
    name = st.text_input(
        "Nom du projet *",
        placeholder="Ex. Suivi piézométrique Champ captant XYZ",
    )
    description = st.text_area(
        "Description",
        placeholder="Contexte, site, objectif de l'étude...",
    )
    share = st.checkbox(
        "Partager avec ma société",
        help=(
            "Le projet reste visible par son créateur tant que cette option "
            "n'est pas activée."
        ),
    )
    submitted = st.form_submit_button("Créer le projet", type="primary")

if submitted:
    try:
        project = projects.create_project(
            user,
            name=name,
            description=description,
            company_id=project_company_id,
            company_name=project_company_name,
            share_with_company=share,
        )
        projects.set_current_project(project["id"], user)
        st.success(f"Projet « {project['projectName']} » créé et ouvert.")
        st.rerun()
    except Exception as exc:
        st.error(f"Impossible de créer le projet : {exc}")

st.divider()

# ---------------------------------------------------------------------------
# Liste des projets accessibles
# ---------------------------------------------------------------------------

st.subheader("Projets accessibles")

try:
    available = projects.list_projects(user)
except Exception as exc:
    st.error(f"Impossible de charger les projets : {exc}")
    available = []

if not available:
    st.info("Aucun projet accessible pour le moment.")
else:
    for project in available:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{project['projectName'] or project['id']}**")
                if project.get("projectDescription"):
                    st.caption(project["projectDescription"])
                details = []
                if project.get("companyName"):
                    details.append(project["companyName"])
                details.append("Partagé" if project.get("projectShare") else "Privé")
                st.caption(" · ".join(details))
            with c2:
                label = "Ouvrir" if project["id"] != (current or {}).get("id") else "Ouvert"
                if st.button(label, key=f"open_project_{project['id']}"):
                    projects.set_current_project(project["id"], user)
                    st.rerun()
