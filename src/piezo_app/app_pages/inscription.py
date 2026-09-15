# -*- coding: utf-8 -*-
"""
Page publique d'inscription à Expert Piézométrie Pro.
"""

import streamlit as st
from firebase_admin import auth as fb_auth

from piezo_app.auth.registration import register_user


def render_registration():
    """Affiche le formulaire d'inscription."""

    st.title("Créer un compte")

    st.markdown(
        """
        Créez votre compte pour accéder à **Expert Piézométrie Pro**.

        Votre compte sera créé en tant qu'**utilisateur standard**.
        Il devra ensuite être activé par un administrateur.
        """
    )

    st.info(
        "Après votre inscription, votre compte restera désactivé "
        "jusqu'à validation par un administrateur."
    )

    with st.form("registration_form"):

        st.subheader("Informations de connexion")

        email = st.text_input(
            "Adresse email",
            placeholder="prenom.nom@entreprise.fr",
        )

        password = st.text_input(
            "Mot de passe",
            type="password",
            help="Minimum 8 caractères.",
        )

        password_confirm = st.text_input(
            "Confirmation du mot de passe",
            type="password",
        )

        st.subheader("Entreprise")

        company_name = st.text_input(
            "Nom de votre société",
            placeholder="Ex. ABC Environnement",
        )

        company_id = st.text_input(
            "Identifiant de votre société",
            placeholder="Ex. ABC",
            help=(
                "Identifiant utilisé par votre organisation "
                "dans l'application."
            ),
        )

        submitted = st.form_submit_button(
            "Créer mon compte",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return

    # ---------------------------------------------------------
    # Validation du formulaire
    # ---------------------------------------------------------

    if not email.strip():
        st.error("Veuillez renseigner votre adresse email.")
        return

    if not password:
        st.error("Veuillez renseigner un mot de passe.")
        return

    if password != password_confirm:
        st.error("Les deux mots de passe ne correspondent pas.")
        return

    if len(password) < 8:
        st.error(
            "Le mot de passe doit contenir au moins 8 caractères."
        )
        return

    if not company_name.strip():
        st.error(
            "Veuillez renseigner le nom de votre société."
        )
        return

    if not company_id.strip():
        st.error(
            "Veuillez renseigner l'identifiant de votre société."
        )
        return

    # ---------------------------------------------------------
    # Création du compte
    # ---------------------------------------------------------

    try:
        register_user(
            email=email,
            password=password,
            company_id=company_id,
            company_name=company_name,
        )

    except fb_auth.EmailAlreadyExistsError:
        st.error(
            "Cette adresse email possède déjà un compte."
        )
        return

    except fb_auth.InvalidEmailError:
        st.error(
            "L'adresse email renseignée n'est pas valide."
        )
        return

    except fb_auth.WeakPasswordError:
        st.error(
            "Le mot de passe est trop faible."
        )
        return

    except Exception:
        st.error(
            "Impossible de créer le compte. "
            "Veuillez réessayer ou contacter l'administrateur."
        )
        return

    # ---------------------------------------------------------
    # Succès
    # ---------------------------------------------------------

    st.success(
        "Votre demande d'inscription a bien été enregistrée."
    )

    st.info(
        "Votre compte est actuellement désactivé. "
        "Un administrateur devra l'activer avant votre première connexion."
    )

    st.page_link(
        "src/piezo_app/app_pages/inscription.py",
        label="Retour à l'inscription",
        icon="🔄",
    )


render_registration()