# -*- coding: utf-8 -*-
"""
Expert Piézométrie Pro — Digital Twin — point d'entrée de l'application.

Ne fait que deux choses : la connexion, puis la navigation entre pages.
Le contenu de chaque page vit dans src/piezo_app/app_pages/ :
  - app_pages/analyse.py : l'application elle-même (tous les rôles)
  - app_pages/admin.py   : gestion des comptes (global_master /
    company_master uniquement — absente de la navigation pour un
    "user" standard, pas seulement inaccessible)

Le code applicatif vit sous src/piezo_app/ (layout src/). La ligne
sys.path ci-dessous rend le package piezo_app importable sans
nécessiter d'installation préalable (`pip install -e .`) : elle
suffit pour `streamlit run app_streamlit.py` en local comme en
déploiement (Streamlit Community Cloud, etc.).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st

from piezo_app.auth import permissions
from piezo_app.components import login
from piezo_app.components.mpl_theme import apply_mpl_theme

st.set_page_config(page_title="Expert Piézométrie Pro", layout="wide")

# Une seule fois, avant toute figure matplotlib créée par les pages/composants.
apply_mpl_theme()

login.require_login()
login.render_user_badge()

pages = [
    st.Page(
        "src/piezo_app/app_pages/analyse.py",
        title="Analyse & Prévision",
        icon="💧",
        default=True,
    ),
]

if permissions.can_administer_users(st.session_state.user):
    pages.append(
        st.Page(
            "src/piezo_app/app_pages/admin.py",
            title="Administration des comptes",
            icon="🔧",
        )
    )

nav = st.navigation(pages)
nav.run()
