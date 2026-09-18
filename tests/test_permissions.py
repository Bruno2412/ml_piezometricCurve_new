# -*- coding: utf-8 -*-
"""
Tests unitaires pour auth/permissions.py.

Module pur (aucun appel réseau, aucune dépendance à Firebase ou
Streamlit) : il ne fait que raisonner sur un dict utilisateur déjà
authentifié. Voir tests/conftest.py pour le mock nécessaire à l'import
du package `auth` (dont dépend indirectement ce module).

Lancer depuis la racine du repo :
    pytest tests/test_permissions.py -v
"""

import pytest

from piezo_app.auth import permissions


def _user(role, company_id=None):
    return {"role": role, "company_id": company_id}


# ─────────────────────────────────────────────────────────────────────────
# is_global_master / is_company_master
# ─────────────────────────────────────────────────────────────────────────


class TestRoleChecks:
    def test_is_global_master_true_for_global_master(self):
        assert permissions.is_global_master(_user(permissions.GLOBAL_MASTER)) is True

    @pytest.mark.parametrize("role", [permissions.COMPANY_MASTER, permissions.USER])
    def test_is_global_master_false_for_other_roles(self, role):
        assert permissions.is_global_master(_user(role)) is False

    def test_is_company_master_true_for_company_master(self):
        assert permissions.is_company_master(_user(permissions.COMPANY_MASTER)) is True

    @pytest.mark.parametrize("role", [permissions.GLOBAL_MASTER, permissions.USER])
    def test_is_company_master_false_for_other_roles(self, role):
        assert permissions.is_company_master(_user(role)) is False


# ─────────────────────────────────────────────────────────────────────────
# can_administer_users
# ─────────────────────────────────────────────────────────────────────────


class TestCanAdministerUsers:
    @pytest.mark.parametrize("role", [permissions.GLOBAL_MASTER, permissions.COMPANY_MASTER])
    def test_admin_roles_can_administer_users(self, role):
        assert permissions.can_administer_users(_user(role)) is True

    def test_standard_user_cannot_administer_users(self):
        assert permissions.can_administer_users(_user(permissions.USER)) is False


# ─────────────────────────────────────────────────────────────────────────
# can_switch_company
# ─────────────────────────────────────────────────────────────────────────


class TestCanSwitchCompany:
    def test_global_master_can_switch_company(self):
        assert permissions.can_switch_company(_user(permissions.GLOBAL_MASTER)) is True

    @pytest.mark.parametrize("role", [permissions.COMPANY_MASTER, permissions.USER])
    def test_other_roles_cannot_switch_company(self, role):
        assert permissions.can_switch_company(_user(role)) is False


# ─────────────────────────────────────────────────────────────────────────
# require_role
# ─────────────────────────────────────────────────────────────────────────


class TestRequireRole:
    def test_passes_silently_when_role_allowed(self):
        # Ne doit lever aucune exception.
        permissions.require_role(_user(permissions.GLOBAL_MASTER), (permissions.GLOBAL_MASTER,))

    def test_raises_permission_error_when_role_not_allowed(self):
        with pytest.raises(PermissionError):
            permissions.require_role(_user(permissions.USER), (permissions.GLOBAL_MASTER,))

    def test_error_message_includes_role_and_allowed_roles(self):
        with pytest.raises(PermissionError, match="user") as exc_info:
            permissions.require_role(
                _user(permissions.USER),
                (permissions.GLOBAL_MASTER, permissions.COMPANY_MASTER),
            )
        assert "global_master" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────
# effective_company_id
# ─────────────────────────────────────────────────────────────────────────


class TestCanCreateUserFor:
    def test_global_master_can_create_company_master_anywhere(self):
        actor = _user(permissions.GLOBAL_MASTER)
        assert permissions.can_create_user_for(actor, permissions.COMPANY_MASTER, "acme") is True

    def test_global_master_can_create_user_anywhere(self):
        actor = _user(permissions.GLOBAL_MASTER)
        assert permissions.can_create_user_for(actor, permissions.USER, "acme") is True

    def test_company_master_can_create_user_for_its_own_company(self):
        actor = _user(permissions.COMPANY_MASTER, company_id="acme")
        assert permissions.can_create_user_for(actor, permissions.USER, "acme") is True

    def test_company_master_cannot_create_user_for_another_company(self):
        actor = _user(permissions.COMPANY_MASTER, company_id="acme")
        assert permissions.can_create_user_for(actor, permissions.USER, "other") is False

    def test_company_master_cannot_create_company_master(self):
        actor = _user(permissions.COMPANY_MASTER, company_id="acme")
        assert permissions.can_create_user_for(actor, permissions.COMPANY_MASTER, "acme") is False

    def test_standard_user_cannot_create_anyone(self):
        actor = _user(permissions.USER, company_id="acme")
        assert permissions.can_create_user_for(actor, permissions.USER, "acme") is False

    @pytest.mark.parametrize("role", [permissions.GLOBAL_MASTER, permissions.COMPANY_MASTER])
    def test_nobody_can_create_a_global_master(self, role):
        actor = _user(role)
        assert permissions.can_create_user_for(actor, permissions.GLOBAL_MASTER, None) is False


# ─────────────────────────────────────────────────────────────────────────
# can_modify_target
# ─────────────────────────────────────────────────────────────────────────


def _target(uid, role, company_id=None):
    return {"uid": uid, "role": role, "company_id": company_id}


class TestCanModifyTarget:
    def test_global_master_can_modify_a_user(self):
        actor = _user(permissions.GLOBAL_MASTER) | {"uid": "gm-1"}
        target = _target("u-1", permissions.USER, "acme")
        assert permissions.can_modify_target(actor, target) is True

    def test_company_master_can_modify_user_of_its_own_company(self):
        actor = _user(permissions.COMPANY_MASTER, company_id="acme") | {"uid": "cm-1"}
        target = _target("u-1", permissions.USER, "acme")
        assert permissions.can_modify_target(actor, target) is True

    def test_company_master_cannot_modify_user_of_another_company(self):
        actor = _user(permissions.COMPANY_MASTER, company_id="acme") | {"uid": "cm-1"}
        target = _target("u-1", permissions.USER, "other")
        assert permissions.can_modify_target(actor, target) is False

    def test_standard_user_cannot_modify_anyone(self):
        actor = _user(permissions.USER, company_id="acme") | {"uid": "u-1"}
        target = _target("u-2", permissions.USER, "acme")
        assert permissions.can_modify_target(actor, target) is False

    def test_nobody_can_modify_a_global_master(self):
        actor = _user(permissions.GLOBAL_MASTER) | {"uid": "gm-1"}
        target = _target("gm-2", permissions.GLOBAL_MASTER)
        assert permissions.can_modify_target(actor, target) is False

    @pytest.mark.parametrize("role", [permissions.GLOBAL_MASTER, permissions.COMPANY_MASTER])
    def test_cannot_modify_own_account(self, role):
        actor = _user(role, company_id="acme") | {"uid": "same-uid"}
        target = _target("same-uid", role, "acme")
        assert permissions.can_modify_target(actor, target) is False


class TestEffectiveCompanyId:
    def test_global_master_gets_viewing_company_id(self):
        user = _user(permissions.GLOBAL_MASTER)
        assert permissions.effective_company_id(user, "acme") == "acme"

    def test_global_master_gets_none_when_nothing_selected(self):
        user = _user(permissions.GLOBAL_MASTER)
        assert permissions.effective_company_id(user, None) is None

    @pytest.mark.parametrize("role", [permissions.COMPANY_MASTER, permissions.USER])
    def test_scoped_roles_always_get_their_own_company(self, role):
        # viewing_company_id est ignoré pour ces rôles : ils ne voient
        # jamais que leur propre société, même si un autre id est passé.
        user = _user(role, company_id="acme")
        assert permissions.effective_company_id(user, "other-company") == "acme"


class TestAllowedPages:
    def test_no_pages_claim_means_everything_allowed(self):
        user = _user(permissions.USER, company_id="acme")
        assert permissions.allowed_pages(user) == set(permissions.PAGE_KEYS)

    def test_only_explicitly_checked_pages_are_allowed(self):
        user = _user(permissions.USER, company_id="acme") | {
            "pages": {"chroniques": True, "analyse": True, "carte": False, "twin": False}
        }
        assert permissions.allowed_pages(user) == {"chroniques", "analyse"}

    def test_empty_pages_dict_means_nothing_allowed(self):
        user = _user(permissions.USER, company_id="acme") | {"pages": {}}
        assert permissions.allowed_pages(user) == set()

    def test_twin_is_dropped_without_analyse(self):
        # Digital Twin réutilise le résultat de fréquence calculé par
        # l'onglet Analyse : il n'a pas de sens seul.
        user = _user(permissions.USER, company_id="acme") | {
            "pages": {"chroniques": False, "analyse": False, "carte": False, "twin": True}
        }
        assert "twin" not in permissions.allowed_pages(user)

    def test_twin_is_kept_when_analyse_is_also_allowed(self):
        user = _user(permissions.USER, company_id="acme") | {
            "pages": {"chroniques": False, "analyse": True, "carte": False, "twin": True}
        }
        assert permissions.allowed_pages(user) == {"analyse", "twin"}
