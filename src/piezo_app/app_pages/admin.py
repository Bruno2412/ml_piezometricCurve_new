# -*- coding: utf-8 -*-
"""
Page « Administration des comptes ».

N'apparaît dans la navigation que pour un global_master ou un
company_master (voir app_streamlit.py, qui construit la liste des
pages selon le rôle). Le contrôle d'accès est aussi vérifié ici, en
seconde ligne de défense, au cas où quelqu'un accéderait à l'URL de
la page directement.

Deux onglets :
  - "Comptes" : gestion des comptes de la société actuellement
    "regardée" (project_selector), visible pour global_master et
    company_master — c'est l'ancien contenu de cette page.
  - "Vue globale" : tableau de contrôle transverse à toutes les
    sociétés, visible uniquement pour un global_master (onglet même
    pas affiché pour un company_master, pas seulement inaccessible).
"""

import streamlit as st

from piezo_app.auth import permissions
from piezo_app.components import project_selector, tab_admin, tab_global_overview

st.title("🔧 Administration des comptes")

if not permissions.can_administer_users(st.session_state.user):
    st.error("Cette page est réservée aux administrateurs.")
    st.stop()

with st.sidebar:
    project_selector.render()

if permissions.is_global_master(st.session_state.user):
    tab_comptes, tab_vue_globale = st.tabs(["Comptes", "🌍 Vue globale"])
    with tab_comptes:
        tab_admin.render()
    with tab_vue_globale:
        tab_global_overview.render()
else:
    tab_admin.render()
