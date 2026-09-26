# -*- coding: utf-8 -*-
"""
Tests pour components/tab_global_overview.py.

Comme pour tab_admin.py, on ne teste pas le rendu Streamlit lui-même,
mais les deux garanties qui comptent vraiment pour cette page :
  1. un non-global_master n'obtient jamais la liste des comptes (Firebase
     n'est même pas interrogée) ;
  2. même avec un clic simulé sur toutes les lignes, seule une action
     autorisée par auth.permissions.can_modify_target() est réellement
     exécutée.
"""

from unittest import mock

import streamlit as st

from piezo_app.auth import permissions
from piezo_app.components import tab_global_overview


def _user_row(uid, role, company_id, company_name=None, disabled=False):
    return {
        "uid": uid,
        "email": f"{uid}@test.fr",
        "role": role,
        "company_id": company_id,
        "company_name": company_name,
        "disabled": disabled,
    }


class TestRenderAccessControl:
    def test_company_master_does_not_trigger_a_users_lookup(self):
        st.session_state.clear()
        st.session_state.user = {
            "uid": "cm-1",
            "role": "company_master",
            "company_id": "acme",
        }

        with (
            mock.patch.object(tab_global_overview.authentication, "list_users") as mocked_list,
            mock.patch("streamlit.info"),
        ):
            tab_global_overview.render()

        mocked_list.assert_not_called()


class TestRenderProtectsAccounts:
    def test_only_authorized_toggles_are_executed(self):
        actor = {"uid": "gm-1", "role": "global_master", "company_id": None}
        visible = [
            _user_row("gm-1", "global_master", None),  # lui-même
            _user_row("gm-2", "global_master", None),  # un autre global_master
            _user_row("cm-1", "company_master", "acme", "ACME"),  # cas normal
            _user_row("u-1", "user", "acme", "ACME"),  # cas normal
        ]

        st.session_state.clear()
        st.session_state.user = actor

        with (
            mock.patch.object(
                tab_global_overview.authentication, "list_users", return_value=visible
            ),
            mock.patch.object(
                tab_global_overview.authentication, "set_user_active"
            ) as mocked_toggle,
            mock.patch.object(
                tab_global_overview.authentication, "set_user_role"
                ),
                mock.patch.object(
                    tab_global_overview.authentication, "set_user_pages"
                ),
            
            mock.patch("streamlit.button", return_value=True),
            mock.patch(
                "streamlit.columns",
                side_effect=lambda spec: [
                    st for _ in (range(spec) if isinstance(spec, int) else spec)
                ],
            ),
            mock.patch(
                "streamlit.selectbox",
                side_effect=lambda label, options=None, **kwargs: (
                    options[0] if options else kwargs.get("options", [None])[0]
                ),
            ),
            mock.patch("streamlit.metric"),
            mock.patch("streamlit.dataframe"),
            mock.patch("streamlit.rerun"),
            mock.patch("streamlit.write"),
            mock.patch("streamlit.subheader"),
            mock.patch("streamlit.divider"),
            mock.patch("streamlit.info"),
        ):
            tab_global_overview.render()

        called_targets = [call.args[1]["uid"] for call in mocked_toggle.call_args_list]
        assert set(called_targets) == {"cm-1", "u-1"}
        for call in mocked_toggle.call_args_list:
            assert permissions.can_modify_target(actor, call.args[1])
