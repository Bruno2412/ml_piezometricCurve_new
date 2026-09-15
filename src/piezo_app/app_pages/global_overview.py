# -*- coding: utf-8 -*-
"""
Page « Vue globale des sociétés ».

N'apparaît dans la navigation que pour un global_master (voir
app_streamlit.py, qui construit la liste des pages selon le rôle). Le
contrôle d'accès est aussi vérifié ici, en seconde ligne de défense, au
cas où quelqu'un accéderait à l'URL de la page directement.
"""

import streamlit as st

from piezo_app.auth import permissions
from piezo_app.components import tab_global_overview

st.title("🌍 Vue globale des sociétés")

if not permissions.is_global_master(st.session_state.user):
    st.error("Cette page est réservée au global_master.")
    st.stop()

tab_global_overview.render()
