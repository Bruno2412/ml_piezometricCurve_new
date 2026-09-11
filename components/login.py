# -*- coding: utf-8 -*-

"""
Écran de connexion + gestion de session utilisateur.

Le module ne contient aucune logique métier.
"""

import streamlit as st

from auth import authentication


def require_login():
    """
    Bloque l'accès à l'application tant que l'utilisateur
    n'est pas authentifié.
    """

    # Initialisation de la session
    if "user" not in st.session_state:
        st.session_state.user = None

    # Utilisateur déjà connecté
    if st.session_state.user is not None:
        return

    # ---------------------------------------------------------
    # FORMULAIRE DE CONNEXION
    # ---------------------------------------------------------

    st.title("Connexion — Expert Piézométrie Pro")

    with st.form("login_form"):

        email = st.text_input(
            "Email",
            placeholder="nom@entreprise.fr",
        )

        password = st.text_input(
            "Mot de passe",
            type="password",
        )

        submitted = st.form_submit_button(
            "Se connecter",
            use_container_width=True,
        )

    if submitted:

        if not email or not password:
            st.error("Veuillez renseigner votre email et votre mot de passe.")
            st.stop()

        with st.spinner("Authentification..."):

            user = authentication.authenticate(
                email=email,
                password=password,
            )

        if user is None:

            st.error(
                "Connexion impossible. "
                "Vérifiez vos identifiants ou contactez votre administrateur."
            )

            st.stop()

        # -----------------------------------------------------
        # SESSION UTILISATEUR
        # -----------------------------------------------------

        st.session_state.user = user

        # Nettoyage éventuel d'une ancienne société consultée
        st.session_state.pop(
            "viewing_company_id",
            None,
        )

        st.rerun()

    st.stop()


def render_user_badge():
    """
    Affiche l'utilisateur connecté dans la sidebar
    et permet la déconnexion.
    """

    user = st.session_state.get("user")

    if user is None:
        return

    label = f"{user['email']} ({user['role']})"

    if user.get("company_name"):
        label += f" — {user['company_name']}"

    st.sidebar.caption(
        f"Connecté : {label}"
    )

    if st.sidebar.button(
        "Se déconnecter",
        use_container_width=True,
    ):

        # Suppression de toutes les informations
        # d'authentification de la session.
        st.session_state.pop(
            "user",
            None,
        )

        st.session_state.pop(
            "viewing_company_id",
            None,
        )

        st.rerun()