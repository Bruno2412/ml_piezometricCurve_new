# -*- coding: utf-8 -*-
"""
Tests pour components/tab_admin.py.

On ne teste pas le rendu Streamlit lui-même (colonnes, boutons), mais
la règle métier qui en dépend le plus directement pour la sécurité :
authentication.set_user_active() ne doit JAMAIS être appelée pour un
compte que auth.permissions.can_modify_target() refuse — sans quoi le
seul garde-fou serait "le bouton ne s'affiche pas", ce qui ne protège
pas contre un rerun avec un st.session_state trafiqué.
"""

from unittest import mock

import streamlit as st

from piezo_app.auth import permissions
from piezo_app.components import tab_admin


def _user_row(uid, role, company_id, disabled=False):
    return {
        "uid": uid,
        "email": f"{uid}@acme.test",
        "role": role,
        "company_id": company_id,
        "company_name": "ACME" if company_id else None,
        "disabled": disabled,
    }


class TestRenderDoesNotExposeProtectedAccounts:
    def test_render_never_calls_set_user_active_on_self_or_global_master(self):
        actor = {
            "uid": "cm-1",
            "role": "company_master",
            "company_id": "acme",
            "company_name": "ACME",
        }
        # Un company_master ne se voit remonter (via list_users) que les
        # comptes de sa propre société, mais on inclut volontairement un
        # global_master et son propre compte pour vérifier que même s'ils
        # apparaissaient dans la liste, aucune action ne serait déclenchée.
        visible = [
            _user_row("cm-1", "company_master", "acme"),  # lui-même
            _user_row("gm-1", "global_master", None),  # un global_master
            _user_row("u-1", "user", "acme"),  # cas normal, autorisé
        ]

        st.session_state.clear()
        st.session_state.user = actor

        with (
            mock.patch.object(tab_admin.authentication, "list_users", return_value=visible),
            mock.patch.object(tab_admin.authentication, "set_user_active") as mocked_toggle,
            mock.patch("streamlit.button", return_value=True),  # simule un clic partout
            mock.patch("streamlit.columns", return_value=[mock.MagicMock() for _ in range(5)]),
            mock.patch("streamlit.form"),
            mock.patch("streamlit.form_submit_button", return_value=False),
            mock.patch("streamlit.text_input", return_value=""),
            mock.patch("streamlit.selectbox", return_value="user"),
            mock.patch("streamlit.checkbox", return_value=False),
            mock.patch("streamlit.caption"),
            mock.patch("streamlit.rerun"),
        ):
            tab_admin.render()

        # Même avec st.button forcé à True pour toutes les lignes, seule
        # la ligne autorisée (u-1) doit avoir déclenché un appel.
        called_targets = [call.args[1]["uid"] for call in mocked_toggle.call_args_list]
        assert called_targets == ["u-1"]
        for call in mocked_toggle.call_args_list:
            assert permissions.can_modify_target(actor, call.args[1])


class TestPagePermissionsForm:
    def test_only_calls_set_user_pages_for_authorized_target(self):
        actor = {
            "uid": "gm-1",
            "role": "global_master",
            "company_id": None,
            "company_name": None,
        }
        visible = [
            _user_row("gm-1", "global_master", None),  # lui-même : pas de popover
            _user_row("u-1", "user", "acme"),  # cas normal
        ]

        st.session_state.clear()
        st.session_state.user = actor

        with (
            mock.patch.object(tab_admin.authentication, "list_users", return_value=visible),
            mock.patch.object(tab_admin.authentication, "set_user_active"),
            mock.patch.object(tab_admin.authentication, "set_user_pages") as mocked_pages,
            mock.patch("streamlit.button", return_value=False),
            mock.patch("streamlit.columns", return_value=[mock.MagicMock() for _ in range(5)]),
            mock.patch("streamlit.form"),
            mock.patch("streamlit.form_submit_button", return_value=True),  # simule "Enregistrer"
            mock.patch("streamlit.text_input", return_value=""),
            mock.patch("streamlit.selectbox", return_value="user"),
            mock.patch("streamlit.checkbox", return_value=True),
            mock.patch("streamlit.caption"),
            mock.patch("streamlit.rerun"),
        ):
            tab_admin.render()

        # Le popover n'est même pas construit sur son propre compte
        # (permissions.can_modify_target renvoie False) : un seul appel,
        # pour u-1.
        called_targets = [call.args[1]["uid"] for call in mocked_pages.call_args_list]
        assert called_targets == ["u-1"]
