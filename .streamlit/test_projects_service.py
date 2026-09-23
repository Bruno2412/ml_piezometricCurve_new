# -*- coding: utf-8 -*-
"""
Created on Wed Sep 23 13:44:20 2026

@author: bruno
"""

import streamlit as st

from piezo_app.services import projects


st.title("Test service Projects")

user = {
    "uid": "4OaXfAiTHNfsSCRkU8EMuJNZjWa2",
    "email": "bruno.vincent33@outlook.com",
    "role": "global_master",
}

try:
    st.write("Utilisateur de test :", user)

    st.write("### 1. list_projects()")

    available = projects.list_projects(user)

    st.success(f"✓ list_projects() fonctionne : {len(available)} projet(s)")

    for project in available:
        st.write(project)

    st.write("### 2. current_project()")

    current = projects.current_project(user)

    if current is None:
        st.info("Aucun projet courant — comportement normal si aucun projet n'est ouvert.")
    else:
        st.success("✓ current_project() fonctionne")
        st.write(current)

except Exception as e:
    st.error("❌ Erreur dans le service Projects")
    st.exception(e)