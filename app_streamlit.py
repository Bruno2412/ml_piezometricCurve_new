# -*- coding: utf-8 -*-
"""
Expert Piézométrie Pro — Digital Twin — point d'entrée de l'application.

Ne fait que deux choses : la connexion, puis la navigation entre pages.
"""

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent / "src"),
)

import requests
import streamlit as st

from piezo_app.auth import permissions, registration
from piezo_app.components import login
from piezo_app.components.mpl_theme import apply_mpl_theme

st.set_page_config(
    page_title="Piézométrie",
    layout="wide",
)


# ---------------------------------------------------------
# Thème Matplotlib
# ---------------------------------------------------------

apply_mpl_theme()


# ---------------------------------------------------------
# Retour du lien de confirmation d'email (Firebase redirige ici
# après clic sur "Confirmer mon email", voir ActionCodeSettings
# dans auth/registration.py avec handle_code_in_app=True). La
# validation réelle (oobCode) n'est déclenchée qu'au clic sur le
# bouton ci-dessous, jamais au simple chargement de cette page —
# ce qui évite qu'un pré-scan de sécurité côté messagerie (ex.
# Outlook Safe Links) ne consomme le lien avant l'utilisateur.
# ---------------------------------------------------------

if st.query_params.get("action") == "email_verified" and st.query_params.get("oobCode"):
    email = st.query_params.get("email")
    oob_code = st.query_params.get("oobCode")

    st.title("Confirmation de votre adresse email")
    st.write(f"Cliquez sur le bouton ci-dessous pour confirmer l'adresse **{email}**.")

    if st.button("Confirmer mon email", type="primary"):
        api_key = st.secrets["firebase"]["api_key"]
        resp = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}",
            json={"oobCode": oob_code},
            timeout=10,
        )

        if resp.status_code == 200:
            st.success("Votre adresse email a bien été validée.")
            st.info(
                "Votre compte est maintenant en attente d'activation par un "
                "administrateur. Vous recevrez un accès dès que votre compte "
                "aura été validé."
            )
            if email:
                try:
                    registration.notify_admins_of_email_confirmation(email)
                except Exception as e:
                    print(f"Échec de notification admin pour {email} : {e}")
        else:
            st.error(
                "Ce lien de confirmation est invalide ou a expiré. "
                "Merci de contacter un administrateur ou de vous réinscrire."
            )

    st.stop()


# ---------------------------------------------------------
# État de connexion
# ---------------------------------------------------------

if "user" not in st.session_state:
    st.session_state.user = None


# =========================================================
# UTILISATEUR NON CONNECTÉ
# =========================================================

if st.session_state.user is None:
    pages = [
        st.Page(
            login.require_login,
            title="Connexion",
            icon="🔐",
            default=True,
        ),
        st.Page(
            "src/piezo_app/app_pages/inscription.py",
            title="Créer un compte",
            icon="📝",
        ),
    ]

    nav = st.navigation(
        pages,
        position="sidebar",
    )

    nav.run()

    st.stop()


# =========================================================
# UTILISATEUR CONNECTÉ
# =========================================================

login.render_user_badge()


pages = [
    st.Page(
        "src/piezo_app/app_pages/analyse.py",
        title="Analyse & Prévision",
        icon="💧",
        default=True,
    ),
]

pages = [
    st.Page(
        "src/piezo_app/app_pages/carto.py",
        title="Cartographie",
        icon=":material/map:",
        default=True,
    ),
]

pages = [
    st.Page(
        "src/piezo_app/app_pages/rapport.py",
        title="Rapport",
        icon=":material/assessment:",
        default=True,
    ),
]


# ---------------------------------------------------------
# Administration
# ---------------------------------------------------------

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
