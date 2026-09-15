# -*- coding: utf-8 -*-

"""
Page publique d'inscription à Expert Piézométrie Pro.
"""

import streamlit as st
from firebase_admin import auth as fb_auth

from piezo_app.auth.authentication import list_companies
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

    # ---------------------------------------------------------
    # Récupération des sociétés existantes
    # ---------------------------------------------------------

    try:
        companies = list_companies()
    except Exception:
        companies = []

    company_options = ["Sélectionnez une société..."]

    company_mapping = {}

    for company in companies:
        company_id = company["company_id"]
        company_name = company["company_name"]

        label = f"{company_name} ({company_id})"

        company_options.append(label)

        company_mapping[label] = {
            "company_id": company_id,
            "company_name": company_name,
        }

    company_options.append("➕ Proposer une nouvelle entreprise")

    # ---------------------------------------------------------
    # Choix de la société
    # ---------------------------------------------------------

    st.subheader("Entreprise")

    selected_company = st.selectbox(
        "Société à rejoindre",
        options=company_options,
        index=0,
        help=(
            "Sélectionnez votre société si elle existe déjà. "
            "Sinon, choisissez « Proposer une nouvelle entreprise »."
        ),
    )

    is_new_company = (
        selected_company == "➕ Proposer une nouvelle entreprise"
    )

    # ---------------------------------------------------------
    # Informations de la nouvelle société
    # ---------------------------------------------------------

    new_company_name = ""
    new_company_id = ""

    if is_new_company:

        st.info(
            "Votre société n'apparaît pas dans la liste ? "
            "Vous pouvez proposer sa création. "
            "Elle devra être validée par un administrateur."
        )

        new_company_name = st.text_input(
            "Nom de votre société",
            placeholder="Ex. ABC Environnement",
        )

        new_company_id = st.text_input(
            "Identifiant de votre société",
            placeholder="Ex. ABC",
            help=(
                "Identifiant court utilisé pour identifier votre "
                "organisation dans l'application."
            ),
        )

    # ---------------------------------------------------------
    # Détermination de la société sélectionnée
    # ---------------------------------------------------------

    if is_new_company:

        company_name = new_company_name.strip()
        company_id = new_company_id.strip()

    elif selected_company in company_mapping:

        selected = company_mapping[selected_company]

        company_name = selected["company_name"]
        company_id = selected["company_id"]

    else:

        company_name = ""
        company_id = ""

    # ---------------------------------------------------------
    # Formulaire d'inscription
    # ---------------------------------------------------------

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

    if not selected_company or selected_company == company_options[0]:
        st.error(
            "Veuillez sélectionner une société ou proposer une "
            "nouvelle entreprise."
        )
        return

    if not company_name:
        st.error(
            "Veuillez renseigner le nom de votre société."
        )
        return

    if not company_id:
        st.error(
            "Veuillez renseigner l'identifiant de votre société."
        )
        return

    # ---------------------------------------------------------
    # Vérification d'un nouvel identifiant de société
    # ---------------------------------------------------------

    if is_new_company:

        existing_company_ids = {
            company["company_id"].strip().lower()
            for company in companies
        }

        if company_id.lower() in existing_company_ids:

            st.error(
                "Cet identifiant de société existe déjà. "
                "Veuillez sélectionner la société correspondante "
                "dans la liste."
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

    if is_new_company:

        st.info(
            f"Votre demande de création de l'entreprise "
            f"« {company_name} » a également été enregistrée. "
            "Un administrateur devra la valider."
        )

    else:

        st.info(
            f"Votre demande de rattachement à "
            f"« {company_name} » a été enregistrée. "
            "Un administrateur devra activer votre compte."
        )

    st.page_link(
        "src/piezo_app/app_pages/inscription.py",
        label="Retour à l'inscription",
        icon="🔄",
    )


render_registration()