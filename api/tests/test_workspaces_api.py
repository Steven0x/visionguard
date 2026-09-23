"""Workspace CRUD + allowlist: admin-only mutations, scoped listing, audit."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.db.session import public_session, tenant_session
from api.app.models.audit import AuditLog
from api.app.models.public import StaffWorkspaceAccess
from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]


def test_admin_create_grants_creator_access_and_audits(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.post(
        "/workspaces",
        headers=auth_header(db.admin_user_id),
        json={"name": "New Agency", "plan": "pro", "contact_email": "x@y.test"},
    )
    assert res.status_code == 201
    ws = res.json()
    assert ws["slug"] == "new-agency"

    with public_session() as s:
        grant = s.scalar(
            select(StaffWorkspaceAccess).where(
                StaffWorkspaceAccess.staff_id == db.admin_staff_id,
                StaffWorkspaceAccess.workspace_id == ws["id"],
            )
        )
    assert grant is not None

    from api.app.db.base import schema_for_workspace

    with tenant_session(schema_for_workspace(ws["id"])) as s:
        actions = set(s.scalars(select(AuditLog.action)).all())
    assert "workspace.created" in actions


def test_reviewer_cannot_create_workspace(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.post(
        "/workspaces",
        headers=auth_header(db.reviewer_a_user_id),
        json={"name": "Nope"},
    )
    assert res.status_code == 403


def test_list_is_scoped_to_access(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.get("/workspaces", headers=auth_header(db.reviewer_a_user_id))
    ids = {w["id"] for w in res.json()}
    assert ids == {db.workspace_a.id}  # reviewer_a is granted only workspace A


def test_admin_patch_updates_and_audits(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace
) -> None:
    res = client.patch(
        f"/workspaces/{new_workspace.id}",
        headers=auth_header(db.admin_user_id),
        json={"contact_name": "Ada", "plan": "enterprise"},
    )
    assert res.status_code == 200
    assert res.json()["contact_name"] == "Ada"
    assert res.json()["plan"] == "enterprise"

    with tenant_session(new_workspace.schema_name) as s:
        actions = set(s.scalars(select(AuditLog.action)).all())
    assert "workspace.updated" in actions


def test_reviewer_cannot_patch_workspace(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    # reviewer_a has access to workspace A but is not an admin.
    res = client.patch(
        f"/workspaces/{db.workspace_a.id}",
        headers=auth_header(db.reviewer_a_user_id),
        json={"contact_name": "x"},
    )
    assert res.status_code == 403


def test_allowlist_add_list_remove(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace
) -> None:
    base = f"/workspaces/{new_workspace.id}/allowlist"
    hdr = auth_header(db.admin_user_id)

    created = client.post(base, headers=hdr, json={"kind": "domain", "value": "ok.example"})
    assert created.status_code == 201
    entry_id = created.json()["id"]

    listed = client.get(base, headers=hdr).json()
    assert any(e["value"] == "ok.example" for e in listed)

    assert client.delete(f"{base}/{entry_id}", headers=hdr).status_code == 204
    assert client.get(base, headers=hdr).json() == []


def test_reviewer_can_view_but_not_mutate_allowlist(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    base = f"/workspaces/{db.workspace_a.id}/allowlist"
    hdr = auth_header(db.reviewer_a_user_id)
    assert client.get(base, headers=hdr).status_code == 200
    assert client.post(base, headers=hdr, json={"kind": "domain", "value": "z"}).status_code == 403
