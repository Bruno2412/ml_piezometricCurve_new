# -*- coding: utf-8 -*-
"""
Expert Piézométrie Pro — Digital Twin — point d'entrée de l'application.

Ne fait que deux choses : la connexion, puis la navigation entre pages.
Le contenu de chaque page vit dans app_pages/ :
  - app_pages/analyse.py : l'application elle-même (tous les rôles)
  - app_pages/admin.py   : gestion des comptes (global_master /
    company_master uniquement — absente de la navigation pour un
    "user" standard, pas seulement inaccessible)
"""

import streamlit as st

from auth import permissions
from components import login

st.set_page_config(page_title="Expert Piézométrie Pro", layout="wide")

login.require_login()
login.render_user_badge()

pages = [
    st.Page("app_pages/analyse.py", title="Analyse & Prévision", icon="💧", default=True),
]

if permissions.can_administer_users(st.session_state.user):
    pages.append(st.Page("app_pages/admin.py", title="Administration des comptes", icon="🔧"))

nav = st.navigation(pages)
nav.run()
