# -*- coding: utf-8 -*-
"""
Page « Administration des comptes ».

N'apparaît dans la navigation que pour un global_master ou un
company_master (voir app_streamlit.py, qui construit la liste des
pages selon le rôle). Le contrôle d'accès est aussi vérifié ici, en
seconde ligne de défense, au cas où quelqu'un accéderait à l'URL de
la page directement.
"""

import streamlit as st

from auth import permissions
from components import project_selector, tab_admin

st.title("🔧 Administration des comptes")

if not permissions.can_administer_users(st.session_state.user):
    st.error("Cette page est réservée aux administrateurs.")
    st.stop()

with st.sidebar:
    project_selector.render()

tab_admin.render()
