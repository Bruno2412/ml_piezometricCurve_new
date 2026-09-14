# -*- coding: utf-8 -*-
"""
Tests unitaires pour auth.authentication._init_firebase().

`_init_firebase()` est déjà exécutée une fois à l'import du module
(mockée globalement par tests/conftest.py, sinon aucun test du module
`auth` ne pourrait s'importer). Ce fichier teste sa logique propre :
qu'elle initialise l'app Firebase avec les credentials de
`st.secrets` quand ce n'est pas encore fait, et surtout qu'elle ne le
refait pas quand `firebase_admin._apps` n'est pas vide (Streamlit
réexécute ce module à chaque rerun, il ne faut jamais réinitialiser
l'app Firebase Admin, ce qui lèverait une ValueError).

Lancer avec :
    pytest tests/test_firebase_init.py -v
"""

from unittest import mock

from auth import authentication


class TestInitFirebase:
    def test_initializes_app_when_not_already_initialized(self):
        with (
            mock.patch.object(authentication.firebase_admin, "_apps", {}),
            mock.patch.object(authentication.credentials, "Certificate") as mock_cert,
            mock.patch.object(authentication.firebase_admin, "initialize_app") as mock_init,
        ):
            authentication._init_firebase()
            mock_cert.assert_called_once()
            mock_init.assert_called_once()

    def test_uses_service_account_from_streamlit_secrets(self):
        with (
            mock.patch.object(authentication.firebase_admin, "_apps", {}),
            mock.patch.object(authentication.credentials, "Certificate") as mock_cert,
            mock.patch.object(authentication.firebase_admin, "initialize_app"),
        ):
            authentication._init_firebase()
            called_with = mock_cert.call_args[0][0]
            assert called_with == dict(authentication.st.secrets["firebase_service_account"])

    def test_does_not_reinitialize_when_app_already_exists(self):
        # firebase_admin._apps non vide => une app existe déjà : on ne
        # doit ni recréer de Certificate, ni rappeler initialize_app.
        with (
            mock.patch.object(authentication.firebase_admin, "_apps", {"[DEFAULT]": mock.Mock()}),
            mock.patch.object(authentication.credentials, "Certificate") as mock_cert,
            mock.patch.object(authentication.firebase_admin, "initialize_app") as mock_init,
        ):
            authentication._init_firebase()
            mock_cert.assert_not_called()
            mock_init.assert_not_called()

    def test_safe_to_call_multiple_times_in_a_row(self):
        # Simule les reruns Streamlit : plusieurs appels successifs ne
        # doivent jamais lever d'erreur.
        with (
            mock.patch.object(authentication.firebase_admin, "_apps", {}),
            mock.patch.object(authentication.credentials, "Certificate"),
            mock.patch.object(authentication.firebase_admin, "initialize_app"),
        ):
            authentication._init_firebase()
            authentication._init_firebase()
            authentication._init_firebase()
