# -*- coding: utf-8 -*-
"""Tests de la couche de contexte/projets sans accès à Firebase réel."""

from unittest import mock

import pytest

from piezo_app.services import projects


class FakeDoc:
    def __init__(self, doc_id, data, exists=True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return self._data


class FakeQuery:
    def __init__(self, docs):
        self.docs = docs

    def where(self, field, operator, value):
        assert operator == "=="
        return FakeQuery(
            [doc for doc in self.docs if doc.to_dict().get(field) == value]
        )

    def stream(self):
        return iter(self.docs)


class FakeCollection(FakeQuery):
    def document(self, doc_id=None):
        return mock.Mock()


def test_list_projects_owner_and_shared_are_deduplicated():
    docs = [
        FakeDoc(
            "p1",
            {
                "projectName": "Projet privé",
                "projectOwner": "u1",
                "projectShare": False,
                "companyId": "c1",
            },
        ),
        FakeDoc(
            "p2",
            {
                "projectName": "Projet partagé",
                "projectOwner": "u2",
                "projectShare": True,
                "companyId": "c1",
            },
        ),
        FakeDoc(
            "p3",
            {
                "projectName": "Projet autre",
                "projectOwner": "u3",
                "projectShare": True,
                "companyId": "c2",
            },
        ),
    ]

    user = {"uid": "u1", "role": "user", "company_id": "c1"}

    with mock.patch.object(projects, "_db", return_value=mock.Mock(collection=lambda _: FakeCollection(docs))):
        result = projects.list_projects(user)

    assert [project["id"] for project in result] == ["p1", "p2"]


def test_global_master_sees_all_projects():
    docs = [
        FakeDoc("p1", {"projectName": "A", "projectOwner": "u1"}),
        FakeDoc("p2", {"projectName": "B", "projectOwner": "u2"}),
    ]
    user = {"uid": "admin", "role": "global_master", "company_id": None}

    with mock.patch.object(projects, "_db", return_value=mock.Mock(collection=lambda _: FakeCollection(docs))):
        result = projects.list_projects(user)

    assert {project["id"] for project in result} == {"p1", "p2"}


def test_get_project_rejects_inaccessible_project():
    doc = FakeDoc(
        "p1",
        {
            "projectName": "Secret",
            "projectOwner": "other",
            "projectShare": False,
            "companyId": "c2",
        },
    )
    user = {"uid": "u1", "role": "user", "company_id": "c1"}

    fake_db = mock.Mock()
    fake_db.collection.return_value.document.return_value.get.return_value = doc

    with mock.patch.object(projects, "_db", return_value=fake_db):
        assert projects.get_project("p1", user) is None


def test_create_project_forces_non_global_user_company():
    user = {
        "uid": "u1",
        "role": "user",
        "company_id": "c1",
        "company_name": "ACME",
    }

    created = FakeDoc(
        "p1",
        {
            "projectName": "Essai",
            "projectDescription": "Test",
            "projectOwner": "u1",
            "projectShare": True,
            "companyId": "c1",
            "companyName": "ACME",
        },
    )

    doc_ref = mock.Mock()
    doc_ref.id = "p1"
    doc_ref.get.return_value = created
    collection = mock.Mock()
    collection.document.return_value = doc_ref
    db = mock.Mock()
    db.collection.return_value = collection

    with mock.patch.object(projects, "_db", return_value=db):
        result = projects.create_project(
            user,
            name="Essai",
            description="Test",
            company_id="other",
            company_name="Autre",
            share_with_company=True,
        )

    assert result["id"] == "p1"
    payload = doc_ref.set.call_args.args[0]
    assert payload["companyId"] == "c1"
    assert payload["projectOwner"] == "u1"


def test_create_project_requires_name_and_company():
    user = {"uid": "u1", "role": "user", "company_id": "c1", "company_name": "ACME"}

    with pytest.raises(projects.ProjectValidationError):
        projects.create_project(user, name="", description="")
