"""Biometrics flag is derived server-side (fail closed) and can't be set by the client."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.app.models.public import Workspace
from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]


def _create(client, auth_header, db, ws, **body):
    return client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json=body,
    )


def test_subject_input_has_no_biometrics_field() -> None:
    # The client cannot even express biometrics_blocked; it is derived server-side.
    from api.app.routers.subjects import SubjectIn

    assert "biometrics_blocked" not in SubjectIn.model_fields


def test_il_residence_is_blocked(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    res = _create(client, auth_header, db, new_workspace, legal_name="A", residence_state="IL")
    assert res.status_code == 201
    assert res.json()["biometrics_blocked"] is True


def test_blank_residence_is_blocked(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    res = _create(client, auth_header, db, new_workspace, legal_name="B")
    assert res.status_code == 201
    assert res.json()["biometrics_blocked"] is True


def test_ca_residence_is_not_blocked(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    res = _create(client, auth_header, db, new_workspace, legal_name="C", residence_state="ca")
    assert res.status_code == 201
    body = res.json()
    assert body["residence_state"] == "CA"
    assert body["biometrics_blocked"] is False


def test_invalid_state_is_rejected(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    res = _create(client, auth_header, db, new_workspace, legal_name="D", residence_state="ZZ")
    assert res.status_code == 422


def test_client_cannot_clear_block_via_patch(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    created = _create(client, auth_header, db, new_workspace, legal_name="E", residence_state="IL")
    sid = created.json()["id"]
    # Send a stray biometrics_blocked=false with IL residence; it must be ignored.
    res = client.patch(
        f"/workspaces/{new_workspace.id}/subjects/{sid}",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "E", "residence_state": "IL", "biometrics_blocked": False},
    )
    assert res.status_code == 200
    assert res.json()["biometrics_blocked"] is True

    # Moving residence to a clearing US state does clear it.
    res = client.patch(
        f"/workspaces/{new_workspace.id}/subjects/{sid}",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "E", "residence_state": "NY"},
    )
    assert res.json()["biometrics_blocked"] is False
