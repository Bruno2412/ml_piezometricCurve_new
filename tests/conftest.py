# -*- coding: utf-8 -*-
"""
Configuration pytest partagée par toute la suite de tests.

`auth/__init__.py` importe `auth.authentication`, qui s'initialise
elle-même (lecture de `st.secrets` + connexion Firebase Admin) au
moment de l'import du module — avant même qu'un test ne s'exécute.
On mocke donc Streamlit et Firebase Admin ici, avant que quoi que ce
soit n'importe `auth`, pour pouvoir tester authentication.py et
permissions.py sans vrais identifiants Firebase ni fichier
.streamlit/secrets.toml.

Ce fichier n'a rien à exporter : son seul rôle est cet effet de bord
au moment de la collecte des tests (conftest.py est toujours importé
par pytest avant les modules de test du même dossier).
"""

from unittest import mock

import streamlit as st

st.secrets = {
    "firebase_service_account": {
        "type": "service_account",
        "project_id": "test-project",
    },
    "firebase": {"api_key": "fake-api-key"},
}

with mock.patch("firebase_admin.credentials.Certificate"), \
     mock.patch("firebase_admin.initialize_app"), \
     mock.patch("firebase_admin._apps", {}):
    import auth  # noqa: F401  (déclenche l'import unique de auth.authentication)
