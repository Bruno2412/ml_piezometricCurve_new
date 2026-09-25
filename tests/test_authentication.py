# -*- coding: utf-8 -*-
"""
Tests unitaires pour auth/authentication.py.

Point clé : ce module contacte Firebase (REST API pour la connexion,
Admin SDK pour la vérification du token et la gestion des comptes).
Rien de tout cela n'est appelé pour de vrai ici — voir tests/conftest.py
pour le mock de l'initialisation Firebase à l'import, et chaque test
mocke individuellement `requests.post` et les fonctions de
`firebase_admin.auth` (importées ici sous le nom `fb_auth`) selon le
scénario voulu.

Lancer depuis la racine du repo :
    pytest tests/test_authentication.py -v
"""

from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from piezo_app.auth import authentication

# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _fake_response(status_code=200, json_data=None):
    """Imite un objet Response de `requests` : un statut et un corps JSON."""
    resp = mock.Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _fake_user_record(
    uid="uid-123", email="user@example.com", disabled=False, email_verified=True, custom_claims=None
):
    """Imite un UserRecord Firebase Admin (seuls les attributs utilisés
    par authentication.py sont présents)."""
    return SimpleNamespace(
        uid=uid,
        email=email,
        disabled=disabled,
        email_verified=email_verified,
        custom_claims=custom_claims,
    )


SIGNIN_SUCCESS_BODY = {
    "idToken": "fake-id-token",
    "localId": "uid-123",
    "refreshToken": "fake-refresh-token",
    "expiresIn": "3600",
}


# ─────────────────────────────────────────────────────────────────────────
# authenticate()
# ─────────────────────────────────────────────────────────────────────────


class TestAuthenticate:
    def test_returns_none_on_network_error(self):
        with mock.patch.object(
            authentication.requests,
            "post",
            side_effect=requests.RequestException("boom"),
        ):
            assert authentication.authenticate("a@b.com", "pw") is None

    def test_returns_none_on_non_200_status(self):
        with mock.patch.object(
            authentication.requests,
            "post",
            return_value=_fake_response(status_code=400),
        ):
            assert authentication.authenticate("a@b.com", "wrong-pw") is None

    def test_returns_none_on_malformed_json_response(self):
        # Réponse 200 mais sans idToken/localId (contrat Firebase rompu).
        with mock.patch.object(
            authentication.requests,
            "post",
            return_value=_fake_response(status_code=200, json_data={"oops": True}),
        ):
            assert authentication.authenticate("a@b.com", "pw") is None

    def test_returns_none_when_token_verification_fails(self):
        with (
            mock.patch.object(
                authentication.requests,
                "post",
                return_value=_fake_response(200, SIGNIN_SUCCESS_BODY),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "verify_id_token",
                side_effect=Exception("token invalide"),
            ),
        ):
            assert authentication.authenticate("a@b.com", "pw") is None

    def test_returns_none_when_uid_mismatch(self):
        # Le uid du token vérifié diffère de celui renvoyé par l'API de
        # connexion : signal d'incohérence, on refuse par sécurité.
        with (
            mock.patch.object(
                authentication.requests,
                "post",
                return_value=_fake_response(200, SIGNIN_SUCCESS_BODY),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "verify_id_token",
                return_value={"uid": "un-autre-uid", "role": "user"},
            ),
        ):
            assert authentication.authenticate("a@b.com", "pw") is None

    def test_returns_none_when_user_record_fetch_fails(self):
        with (
            mock.patch.object(
                authentication.requests,
                "post",
                return_value=_fake_response(200, SIGNIN_SUCCESS_BODY),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "verify_id_token",
                return_value={"uid": "uid-123", "role": "user"},
            ),
            mock.patch.object(
                authentication.fb_auth,
                "get_user",
                side_effect=Exception("compte introuvable"),
            ),
        ):
            assert authentication.authenticate("a@b.com", "pw") is None

    def test_returns_none_when_account_disabled(self):
        with (
            mock.patch.object(
                authentication.requests,
                "post",
                return_value=_fake_response(200, SIGNIN_SUCCESS_BODY),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "verify_id_token",
                return_value={"uid": "uid-123", "role": "user"},
            ),
            mock.patch.object(
                authentication.fb_auth,
                "get_user",
                return_value=_fake_user_record(disabled=True),
            ),
        ):
            assert authentication.authenticate("a@b.com", "pw") is None

    def test_returns_none_when_role_missing_in_claims(self):
        with (
            mock.patch.object(
                authentication.requests,
                "post",
                return_value=_fake_response(200, SIGNIN_SUCCESS_BODY),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "verify_id_token",
                return_value={"uid": "uid-123"},  # pas de "role"
            ),
            mock.patch.object(
                authentication.fb_auth,
                "get_user",
                return_value=_fake_user_record(),
            ),
        ):
            assert authentication.authenticate("a@b.com", "pw") is None

    def test_success_returns_expected_profile(self):
        decoded_token = {
            "uid": "uid-123",
            "role": "company_master",
            "company_id": "acme",
            "company_name": "ACME Corp",
        }
        with (
            mock.patch.object(
                authentication.requests,
                "post",
                return_value=_fake_response(200, SIGNIN_SUCCESS_BODY),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "verify_id_token",
                return_value=decoded_token,
            ),
            mock.patch.object(
                authentication.fb_auth,
                "get_user",
                return_value=_fake_user_record(email="chef@acme.com"),
            ),
        ):
            result = authentication.authenticate("chef@acme.com", "pw")

        assert result == {
            "uid": "uid-123",
            "email": "chef@acme.com",
            "role": "company_master",
            "company_id": "acme",
            "company_name": "ACME Corp",
            "pages": {},
            "id_token": "fake-id-token",
            "refresh_token": "fake-refresh-token",
            "expires_in": "3600",
        }

    def test_email_is_stripped_before_sending(self):
        with (
            mock.patch.object(
                authentication.requests,
                "post",
                return_value=_fake_response(200, SIGNIN_SUCCESS_BODY),
            ) as mocked_post,
            mock.patch.object(
                authentication.fb_auth,
                "verify_id_token",
                return_value={"uid": "uid-123", "role": "user"},
            ),
            mock.patch.object(
                authentication.fb_auth,
                "get_user",
                return_value=_fake_user_record(),
            ),
        ):
            authentication.authenticate("  chef@acme.com  ", "pw")

        sent_payload = mocked_post.call_args.kwargs["json"]
        assert sent_payload["email"] == "chef@acme.com"


# ─────────────────────────────────────────────────────────────────────────
# create_user()
# ─────────────────────────────────────────────────────────────────────────


def _global_master(uid="gm-1"):
    return {"uid": uid, "role": "global_master", "company_id": None}


def _company_master(company_id="acme", uid="cm-1"):
    return {"uid": uid, "role": "company_master", "company_id": company_id}


class TestCreateUser:
    # Remarque : le cas "global_master + company_id -> ValueError" a
    # disparu, car il est désormais intercepté plus tôt par la
    # vérification des droits (test_nobody_can_create_a_global_master
    # ci-dessous) : personne ne peut créer de global_master par ce
    # chemin, avec ou sans company_id.

    @pytest.mark.parametrize("role", ["company_master", "user"])
    def test_scoped_role_without_company_id_raises_value_error(self, role):
        with pytest.raises(ValueError):
            authentication.create_user(_global_master(), "a@b.com", "pw", role, company_id=None)

    def test_nobody_can_create_a_global_master(self):
        # La création de global_master reste hors du périmètre de
        # l'admin (2 comptes de bootstrap, voir create_first_users.py) :
        # même un global_master ne peut pas en créer un via ce chemin.
        with pytest.raises(PermissionError):
            authentication.create_user(_global_master(), "a@b.com", "pw", "global_master")

    def test_company_master_cannot_create_company_master(self):
        with pytest.raises(PermissionError):
            authentication.create_user(
                _company_master(), "a@b.com", "pw", "company_master", company_id="acme"
            )

    def test_company_master_cannot_create_user_for_another_company(self):
        with pytest.raises(PermissionError):
            authentication.create_user(
                _company_master(company_id="acme"),
                "a@b.com",
                "pw",
                "user",
                company_id="other-company",
            )

    def test_global_master_creates_company_scoped_user_with_company_claims(self):
        with (
            mock.patch.object(
                authentication.fb_auth,
                "create_user",
                return_value=_fake_user_record(uid="new-uid"),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "set_custom_user_claims",
            ) as mocked_set_claims,
        ):
            authentication.create_user(
                _global_master(),
                "a@b.com",
                "pw",
                "user",
                company_id="acme",
                company_name="ACME Corp",
            )

        mocked_set_claims.assert_called_once_with(
            "new-uid",
            {"role": "user", 
             "company_id": "acme", 
             "company_name": "ACME Corp"
            },
            app=authentication._firebase_app,
        )

    def test_company_master_creates_user_for_its_own_company(self):
        with (
            mock.patch.object(
                authentication.fb_auth,
                "create_user",
                return_value=_fake_user_record(uid="new-uid"),
            ),
            mock.patch.object(
                authentication.fb_auth,
                "set_custom_user_claims",
            ) as mocked_set_claims,
        ):
            authentication.create_user(
                _company_master(company_id="acme"),
                "a@b.com",
                "pw",
                "user",
                company_id="acme",
                company_name="ACME Corp",
            )

        mocked_set_claims.assert_called_once_with(
            "new-uid",
            {"role": "user", 
             "company_id": "acme", 
             "company_name": "ACME Corp"
            },
            app=authentication._firebase_app,
        )


# ─────────────────────────────────────────────────────────────────────────
# list_users()
# ─────────────────────────────────────────────────────────────────────────


class TestListUsers:
    def _fake_page(self, users):
        page = mock.Mock()
        page.iterate_all.return_value = iter(users)
        return page

    def test_raises_permission_error_for_standard_user(self):
        with pytest.raises(PermissionError):
            authentication.list_users({"role": "user"})

    def test_global_master_sees_all_companies(self):
        users = [
            SimpleNamespace(
                uid="1",
                email="a@acme.com",
                disabled=False,
                custom_claims={"role": "user", "company_id": "acme"},
            ),
            SimpleNamespace(
                uid="2",
                email="b@other.com",
                disabled=True,
                custom_claims={"role": "company_master", "company_id": "other"},
            ),
        ]
        with mock.patch.object(
            authentication.fb_auth,
            "list_users",
            return_value=self._fake_page(users),
        ):
            result = authentication.list_users({"role": "global_master"})

        assert {u["company_id"] for u in result} == {"acme", "other"}
        assert len(result) == 2

    def test_company_master_sees_only_own_company(self):
        users = [
            SimpleNamespace(
                uid="1",
                email="a@acme.com",
                disabled=False,
                custom_claims={"role": "user", "company_id": "acme"},
            ),
            SimpleNamespace(
                uid="2",
                email="b@other.com",
                disabled=False,
                custom_claims={"role": "user", "company_id": "other"},
            ),
        ]
        current_user = {"role": "company_master", "company_id": "acme"}
        with mock.patch.object(
            authentication.fb_auth,
            "list_users",
            return_value=self._fake_page(users),
        ):
            result = authentication.list_users(current_user)

        assert len(result) == 1
        assert result[0]["company_id"] == "acme"

    def test_skips_users_without_role_claim(self):
        users = [
            SimpleNamespace(uid="1", email="pending@acme.com", disabled=False, custom_claims=None),
        ]
        with mock.patch.object(
            authentication.fb_auth,
            "list_users",
            return_value=self._fake_page(users),
        ):
            result = authentication.list_users({"role": "global_master"})

        assert result == []


# ─────────────────────────────────────────────────────────────────────────
# set_user_active()
# ─────────────────────────────────────────────────────────────────────────


class TestSetUserActive:
    def test_global_master_deactivates_a_user(self):
        target = {"uid": "uid-1", "role": "user", "company_id": "acme"}
        with mock.patch.object(authentication.fb_auth, "update_user") as mocked:
            authentication.set_user_active(_global_master(), target, is_active=False)
        mocked.assert_called_once_with("uid-1", disabled=True)

    def test_global_master_reactivates_a_user(self):
        target = {"uid": "uid-1", "role": "user", "company_id": "acme"}
        with mock.patch.object(authentication.fb_auth, "update_user") as mocked:
            authentication.set_user_active(_global_master(), target, is_active=True)
        mocked.assert_called_once_with("uid-1", disabled=False)

    def test_company_master_deactivates_user_of_its_own_company(self):
        actor = _company_master(company_id="acme")
        target = {"uid": "uid-1", "role": "user", "company_id": "acme"}
        with mock.patch.object(authentication.fb_auth, "update_user") as mocked:
            authentication.set_user_active(actor, target, is_active=False)
        mocked.assert_called_once_with("uid-1", disabled=True)

    def test_company_master_cannot_deactivate_user_of_another_company(self):
        actor = _company_master(company_id="acme")
        target = {"uid": "uid-1", "role": "user", "company_id": "other-company"}
        with mock.patch.object(authentication.fb_auth, "update_user") as mocked:
            with pytest.raises(PermissionError):
                authentication.set_user_active(actor, target, is_active=False)
        mocked.assert_not_called()

    def test_nobody_can_deactivate_a_global_master(self):
        actor = _global_master(uid="gm-1")
        target = _global_master(uid="gm-2")
        with mock.patch.object(authentication.fb_auth, "update_user") as mocked:
            with pytest.raises(PermissionError):
                authentication.set_user_active(actor, target, is_active=False)
        mocked.assert_not_called()

    def test_cannot_deactivate_own_account(self):
        actor = _company_master(company_id="acme", uid="cm-1")
        with mock.patch.object(authentication.fb_auth, "update_user") as mocked:
            with pytest.raises(PermissionError):
                authentication.set_user_active(actor, actor, is_active=False)
        mocked.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────
# set_user_pages()
# ─────────────────────────────────────────────────────────────────────────


class TestSetUserPages:
    def test_global_master_sets_pages_for_a_user(self):
        target = {"uid": "uid-1", "role": "user", "company_id": "acme"}
        with (
            mock.patch.object(
                authentication.fb_auth,
                "get_user",
                return_value=_fake_user_record(
                    custom_claims={"role": "user", "company_id": "acme"}
                ),
            ),
            mock.patch.object(authentication.fb_auth, "set_custom_user_claims") as mocked_set,
        ):
            authentication.set_user_pages(
                _global_master(), target, {"chroniques": True, "analyse": True}
            )

        mocked_set.assert_called_once_with(
            "uid-1",
            {
                "role": "user",
                "company_id": "acme",
                "pages": {
                    "chroniques": True,
                    "analyse": True,
                    "carte": False,
                    "twin": False,
                },
            },
            app=authentication._firebase_app,
        )

    def test_company_master_cannot_set_pages_for_another_company(self):
        actor = _company_master(company_id="acme")
        target = {"uid": "uid-1", "role": "user", "company_id": "other-company"}
        with (
            mock.patch.object(authentication.fb_auth, "get_user") as mocked_get,
            mock.patch.object(authentication.fb_auth, "set_custom_user_claims") as mocked_set,
        ):
            with pytest.raises(PermissionError):
                authentication.set_user_pages(actor, target, {"chroniques": True})
        mocked_get.assert_not_called()
        mocked_set.assert_not_called()

    def test_nobody_can_set_pages_of_a_global_master(self):
        actor = _global_master(uid="gm-1")
        target = _global_master(uid="gm-2")
        with (
            mock.patch.object(authentication.fb_auth, "get_user") as mocked_get,
            mock.patch.object(authentication.fb_auth, "set_custom_user_claims") as mocked_set,
        ):
            with pytest.raises(PermissionError):
                authentication.set_user_pages(actor, target, {"chroniques": True})
        mocked_get.assert_not_called()
        mocked_set.assert_not_called()

    def test_cannot_set_own_pages(self):
        actor = _company_master(company_id="acme", uid="cm-1")
        with (
            mock.patch.object(authentication.fb_auth, "get_user") as mocked_get,
            mock.patch.object(authentication.fb_auth, "set_custom_user_claims") as mocked_set,
        ):
            with pytest.raises(PermissionError):
                authentication.set_user_pages(actor, actor, {"chroniques": True})
        mocked_get.assert_not_called()
        mocked_set.assert_not_called()
