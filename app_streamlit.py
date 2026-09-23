# -*- coding: utf-8 -*-
"""
Expert Piézométrie Pro — Digital Twin — point d'entrée de l'application.

Ne fait que trois choses : la connexion, la resynchronisation régulière
des droits de l'utilisateur connecté, puis la navigation entre pages.
"""

import sys
import time
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent / "src"),
)

import requests
import streamlit as st

from piezo_app.auth import authentication, permissions, registration
from piezo_app.components import login, project_selector
from piezo_app.services import projects
from piezo_app.components.mpl_theme import apply_mpl_theme

st.set_page_config(
    page_title="Piézométrie",
    layout="wide",
)

# Intervalle minimal (en secondes) entre deux relectures des droits
# depuis Firebase pour un utilisateur connecté.
_CLAIMS_REFRESH_EVERY_S = 60


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
#
# L'adresse email transmise aux administrateurs est celle renvoyée par
# Firebase après validation du code, jamais celle du paramètre d'URL
# (modifiable par n'importe qui).
# ---------------------------------------------------------

if st.query_params.get("action") == "email_verified" and st.query_params.get("oobCode"):
    oob_code = st.query_params.get("oobCode")

    st.title("Confirmation de votre adresse email")
    st.write("Cliquez sur le bouton ci-dessous pour confirmer votre adresse email.")

    if st.button("Confirmer mon email", type="primary"):
        api_key = st.secrets["firebase"]["api_key"]

        try:
            resp = requests.post(
                f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}",
                json={"oobCode": oob_code},
                timeout=10,
            )
        except requests.RequestException:
            st.error(
                "Impossible de joindre le service de confirmation. "
                "Réessayez dans un instant."
            )
            st.stop()

        if resp.status_code == 200:
            try:
                verified_email = resp.json().get("email")
            except ValueError:
                verified_email = None

            if verified_email:
                st.success(f"L'adresse {verified_email} a bien été validée.")
            else:
                st.success("Votre adresse email a bien été validée.")

            st.info(
                "Votre compte est maintenant en attente d'activation par un "
                "administrateur. Vous recevrez un accès dès que votre compte "
                "aura été validé."
            )

            if verified_email:
                try:
                    registration.notify_admins_of_email_confirmation(verified_email)
                except Exception as e:
                    print(f"Échec de notification admin pour {verified_email} : {e}")
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

# ---------------------------------------------------------
# Resynchronisation des droits : les claims (rôle, société, pages)
# sont copiés dans la session au login. On les relit ici au plus une
# fois par minute pour qu'un changement de droits ou une désactivation
# de compte soit pris en compte sans reconnexion.
# ---------------------------------------------------------

_now = time.time()

if _now - st.session_state.get("_claims_checked_at", 0.0) > _CLAIMS_REFRESH_EVERY_S:
    _fresh_user = authentication.refresh_session_user(st.session_state.user)
    st.session_state["_claims_checked_at"] = _now

    if _fresh_user is None:
        # Compte supprimé, désactivé ou sans rôle : retour à la connexion.
        st.session_state.user = None
        st.rerun()

    st.session_state.user = _fresh_user

login.render_user_badge()
project_selector.render()

user = st.session_state.user
current_project = projects.current_project(user)
allowed = permissions.allowed_pages(user)


pages = [
    st.Page(
        "src/piezo_app/app_pages/projets.py",
        title="Projets",
        icon="📁",
        default=True,
    ),
]

# Les pages métier ne sont proposées qu'après ouverture d'un projet.
# Le contrôle est également effectué à l'intérieur des pages elles-mêmes
# pour éviter tout contournement par une navigation directe.
if current_project is not None:
    pages.append(
        st.Page(
            "src/piezo_app/app_pages/analyse.py",
            title="Analyse & Prévision",
            icon="💧",
            default=False,
        )
    )

    if allowed:
        pages += [
            st.Page(
                "src/piezo_app/app_pages/carto.py",
                title="Cartographie",
                icon=":material/map:",
            ),
            st.Page(
                "src/piezo_app/app_pages/rapport.py",
                title="Rapport",
                icon=":material/assessment:",
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
