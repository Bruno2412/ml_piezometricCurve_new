# -*- coding: utf-8 -*-
"""Sélecteur de société, visible uniquement pour un global_master.

Un company_master ou un user reste cantonné à sa propre société (pas de
sélecteur affiché) ; un global_master choisit ici quelle société il
regarde, et ce choix est stocké dans st.session_state['viewing_company_id']
pour le reste du script (voir auth.permissions.effective_company_id).

À appeler juste après login.render_user_badge(), dans la sidebar :

    from components import project_selector
    project_selector.render()
"""

import streamlit as st

from auth import authentication, permissions


def render():
    user = st.session_state.user

    if not permissions.can_switch_company(user):
        return  # company_master / user : rien à afficher, société fixe

    if "viewing_company_id" not in st.session_state:
        st.session_state.viewing_company_id = None

    # Les sociétés connues sont déduites des comptes existants (pas de
    # collection "companies" séparée pour l'instant — simple tant que
    # le nombre de sociétés reste petit).
    try:
        all_users = authentication.list_users(user)
    except PermissionError:
        st.sidebar.error("Impossible de charger la liste des sociétés.")
        return

    companies = {}
    for u in all_users:
        if u["company_id"]:
            companies[u["company_id"]] = u["company_name"]

    if not companies:
        st.sidebar.info("Aucune société créée pour l'instant.")
        return

    options = list(companies.keys())
    labels = {cid: companies[cid] for cid in options}

    selected = st.sidebar.selectbox(
        "Société consultée",
        options=options,
        format_func=lambda cid: labels[cid],
        index=options.index(st.session_state.viewing_company_id)
        if st.session_state.viewing_company_id in options else 0,
    )
    st.session_state.viewing_company_id = selected
