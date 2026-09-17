# -*- coding: utf-8 -*-
"""
auth/authentication.py — Connexion à Firebase Authentication et gestion
des comptes.

Rôles :
  - global_master   : voit toutes les sociétés
  - company_master  : administre une société
  - user            : utilisateur standard

L'activation d'un compte repose sur deux leviers indépendants,
appliqués séparément par l'administrateur dans tab_global_overview.py :
  - disabled (set_user_active) : le compte peut se connecter ou non ;
  - pages (set_user_pages) : ce que le compte peut voir une fois
    connecté.

Le claim "approved" n'est plus utilisé pour bloquer la connexion.
"""

import firebase_admin
import requests
import streamlit as st

from firebase_admin import auth as fb_auth
from firebase_admin import credentials

from piezo_app.auth import permissions


def _init_firebase():
    """
    Initialise Firebase Admin une seule fois.
    """

    if firebase_admin._apps:
        return firebase_admin.get_app()

    cred_dict = dict(
        st.secrets["firebase_service_account"]
    )

    cred = credentials.Certificate(
        cred_dict
    )

    return firebase_admin.initialize_app(
        cred
    )


_init_firebase()


_API_KEY = st.secrets["firebase"]["api_key"]

_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/"