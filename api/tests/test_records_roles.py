"""Role enforcement: admin-only revokes + authorization ops; reviewers create/view."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]
_PDF = b"%PDF-1.4 doc"


def _subject_in_a(client, auth_header, db) -> int:
    return client.post(
        f"/workspaces/{db.workspace_a.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Role Subject"},
    ).json()["id"]


def _create_rights(client, auth_header, db, sid, who):
    return client.post(
        f"/workspaces/{db.workspace_a.id}/subjects/{sid}/rights",
        headers=auth_header(who),
        data={"type": "self_owned_declaration", "grants_enforcement_right": "false"},
        files={"file": ("d.pdf", _PDF, "application/octet-stream")},
    )


def test_reviewer_can_create_rights_but_not_revoke(
    client: TestClient, auth_header: Header, db: Fixtures
):
    sid = _subject_in_a(client, auth_header, db)
    # reviewer_a has access to workspace A and may create rights.
    created = _create_rights(client, auth_header, db, sid, db.reviewer_a_user_id)
    assert created.status_code == 201
    rid = created.json()["id"]

    # ...but only an admin may revoke.
    denied = client.post(
        f"/workspaces/{db.workspace_a.id}/subjects/{sid}/rights/{rid}/revoke",
        headers=auth_header(db.reviewer_a_user_id),
        json={"reason": "x"},
    )
    assert denied.status_code == 403
    allowed = client.post(
        f"/workspaces/{db.workspace_a.id}/subjects/{sid}/rights/{rid}/revoke",
        headers=auth_header(db.admin_user_id),
        json={"reason": "x"},
    )
    assert allowed.status_code == 200


def test_reviewer_cannot_revoke_consent(client: TestClient, auth_header: Header, db: Fixtures):
    sid = _subject_in_a(client, auth_header, db)
    created = client.post(
        f"/workspaces/{db.workspace_a.id}/subjects/{sid}/consent",
        headers=auth_header(db.reviewer_a_user_id),
        data={"type": "enforcement", "signer_name": "S", "signed_date": "2026-01-01"},
        files={"file": ("c.pdf", _PDF, "application/octet-stream")},
    )
    assert created.status_code == 201  # reviewers may create consent
    cid = created.json()["id"]

    denied = client.post(
        f"/workspaces/{db.workspace_a.id}/subjects/{sid}/consent/{cid}/revoke",
        headers=auth_header(db.reviewer_a_user_id),
        json={"reason": "x"},
    )
    assert denied.status_code == 403


def test_authorization_ops_are_admin_only(client: TestClient, auth_header: Header, db: Fixtures):
    denied = client.post(
        f"/workspaces/{db.workspace_a.id}/authorizations",
        headers=auth_header(db.reviewer_a_user_id),
        data={"signer_name": "S", "authorized_date": "2026-01-01"},
    )
    assert denied.status_code == 403

    created = client.post(
        f"/workspaces/{db.workspace_a.id}/authorizations",
        headers=auth_header(db.admin_user_id),
        data={"signer_name": "S", "authorized_date": "2026-01-01"},
    )
    assert created.status_code == 201
    aid = created.json()["id"]

    denied_revoke = client.post(
        f"/workspaces/{db.workspace_a.id}/authorizations/{aid}/revoke",
        headers=auth_header(db.reviewer_a_user_id),
        json={"reason": "x"},
    )
    assert denied_revoke.status_code == 403
