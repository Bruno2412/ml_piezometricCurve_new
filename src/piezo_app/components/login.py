# -*- coding: utf-8 -*-

"""
Écran de connexion et gestion de la session utilisateur.
"""

import logging

import streamlit as st

from piezo_app.auth import authentication


logger = logging.getLogger(__name__)


# ============================================================================
# CONNEXION
# ============================================================================

def require_login():
    """
    Bloque l'accès à l'application tant que l'utilisateur
    n'est pas authentifié.
    """

    # ------------------------------------------------------------------
    # Initialisation de la session
    # ------------------------------------------------------------------

    if "user" not in st.session_state:
        st.session_state.user = None

    # ------------------------------------------------------------------
    # Utilisateur déjà connecté
    # ------------------------------------------------------------------

    if st.session_state.user is not None:
        return

    # ------------------------------------------------------------------
    # FORMULAIRE
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Inscription
    # ------------------------------------------------------------------

    st.page_link(
        "src/piezo_app/app_pages/inscription.py",
        label="Pas encore de compte ? Créer un compte",
        icon="📝",
    )

    # ------------------------------------------------------------------
    # Traitement de la connexion
    # ------------------------------------------------------------------

    if submitted:

        email = email.strip()

        if not email or not password:
            st.error(
                "Veuillez renseigner votre email et votre mot de passe."
            )
            st.stop()

        with st.spinner("Authentification..."):

            try:
                user = authentication.authenticate(
                    email=email,
                    password=password,
                )

            except Exception:
                logger.exception(
                    "Erreur inattendue pendant l'authentification."
                )
                user = None

        # --------------------------------------------------------------
        # Échec
        # --------------------------------------------------------------

        if user is None:
            st.error(
                "Connexion impossible. Vérifiez vos identifiants ou "
                "contactez votre administrateur."
            )
            st.stop()

        # --------------------------------------------------------------
        # Connexion réussie
        # --------------------------------------------------------------

        st.session_state.user = user

        # Nettoyage de quelques éventuelles anciennes données de session.
        #
        # On ne fait PAS st.session_state.clear() ici car cela supprimerait
        # immédiatement la session utilisateur que nous venons de créer.
        st.session_state.pop("shared_map_data", None)
        st.session_state.pop("active_project", None)

        st.rerun()

    # ------------------------------------------------------------------
    # Tant que l'utilisateur n'est pas connecté :
    # arrêt du rendu de l'application.
    # ------------------------------------------------------------------

    st.stop()


# ============================================================================
# BADGE UTILISATEUR
# ============================================================================

def render_user_badge():
    """
    Affiche l'utilisateur connecté dans la sidebar
    et permet la déconnexion.
    """

    user = st.session_state.get("user")

    if user is None:
        return

    # ------------------------------------------------------------------
    # Informations utilisateur
    # ------------------------------------------------------------------

    email = user.get("email", "?")
    role = user.get("role", "?")

    label = f"{email} ({role})"

    if user.get("company_name"):
        label += f" — {user['company_name']}"

    st.sidebar.caption(
        f"Connecté : {label}"
    )

    # ------------------------------------------------------------------
    # Déconnexion
    # ------------------------------------------------------------------

    if st.sidebar.button(
        "Se déconnecter",
        use_container_width=True,
    ):

        # On vide toute la session afin qu'un autre utilisateur
        # ne puisse pas récupérer des données du précédent compte.
        st.session_state.clear()

        st.rerun()