# -*- coding: utf-8 -*-
"""Écran de connexion + badge utilisateur / déconnexion.

À appeler tout en haut de app_streamlit.py, avant tout autre contenu :

    from components import login
    login.require_login()
    login.render_user_badge()
"""

import streamlit as st

from auth import authentication


def require_login():
    """Bloque l'accès au reste de l'app tant que l'utilisateur n'est pas
    authentifié."""
    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user is not None:
        return  # déjà connecté, on laisse l'app continuer

    st.title("Connexion — Expert Piézométrie Pro")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter")

    if submitted:
        user = authentication.authenticate(email, password)
        if user is None:
            st.error("Email ou mot de passe incorrect, ou compte non configuré.")
        else:
            st.session_state.user = user
            st.rerun()

    st.stop()


def render_user_badge():
    """Affiche l'utilisateur connecté + bouton de déconnexion dans la
    sidebar. À appeler juste après require_login()."""
    user = st.session_state.user
    label = f"{user['email']} ({user['role']})"
    if user.get("company_name"):
        label += f" — {user['company_name']}"
    st.sidebar.caption(f"Connecté : {label}")
    if st.sidebar.button("Se déconnecter"):
        st.session_state.user = None
        st.session_state.pop("viewing_company_id", None)
        st.rerun()
