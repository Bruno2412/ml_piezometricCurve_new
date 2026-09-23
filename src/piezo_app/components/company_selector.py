# -*- coding: utf-8 -*-
"""Sélecteur de société pour le global_master.

Ce composant reprend l'ancien sélecteur qui occupait le fichier
``project_selector.py``. Il reste utilisé par l'administration des comptes.
Le contexte projet est désormais géré séparément par ``project_selector``.
"""

import streamlit as st

from piezo_app.auth import authentication, permissions


def render() -> None:
    """Affiche le sélecteur de société uniquement pour global_master."""
    user = st.session_state.user

    if not permissions.can_switch_company(user):
        return

    if "viewing_company_id" not in st.session_state:
        st.session_state.viewing_company_id = None

    try:
        all_users = authentication.list_users(user)
    except PermissionError:
        st.sidebar.error("Impossible de charger la liste des sociétés.")
        return

    companies = {}
    for account in all_users:
        if account["company_id"]:
            companies[account["company_id"]] = account["company_name"]

    if not companies:
        st.sidebar.info("Aucune société créée pour l'instant.")
        return

    options = list(companies.keys())
    labels = {cid: companies[cid] for cid in options}

    selected = st.sidebar.selectbox(
        "Société consultée",
        options=options,
        format_func=lambda cid: labels[cid],
        index=(
            options.index(st.session_state.viewing_company_id)
            if st.session_state.viewing_company_id in options
            else 0
        ),
        key="viewing_company_selector",
    )
    st.session_state.viewing_company_id = selected
