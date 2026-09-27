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


# ── Error handling / validation (fix branch) ──────────────────────────────────

_ORIGIN = "http://localhost:5173"  # matches ALLOWED_ORIGINS so CORS headers apply


def test_unhandled_error_returns_cors_headers_and_json(
    client: TestClient, auth_header: Header, db: Fixtures, monkeypatch
) -> None:
    """A 500 must still carry CORS headers + a JSON body, so the UI shows the real error
    instead of an opaque 'Failed to fetch'."""
    import api.app.routers.workspaces as wsr

    def _boom(**kwargs):
        raise RuntimeError("provisioning exploded")

    monkeypatch.setattr(wsr.ws_service, "create_workspace_with_access", _boom)
    res = client.post(
        "/workspaces",
        headers={**auth_header(db.admin_user_id), "Origin": _ORIGIN},
        json={"name": "Boom Agency", "plan": "starter"},
    )
    assert res.status_code == 500
    assert res.headers.get("access-control-allow-origin") == _ORIGIN
    assert res.json()["detail"]  # a readable body, not a dropped connection


def test_invalid_plan_is_rejected_inline(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.post(
        "/workspaces",
        headers={**auth_header(db.admin_user_id), "Origin": _ORIGIN},
        json={"name": "RealTime Testers", "plan": "first"},  # "first" is not a valid plan
    )
    assert res.status_code == 422
    assert res.headers.get("access-control-allow-origin") == _ORIGIN
    assert "plan" in res.text.lower()


def test_blank_name_is_rejected(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.post(
        "/workspaces",
        headers=auth_header(db.admin_user_id),
        json={"name": "", "plan": "starter"},
    )
    assert res.status_code == 422


def test_duplicate_workspace_name_returns_409(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    hdr = {**auth_header(db.admin_user_id), "Origin": _ORIGIN}
    first = client.post("/workspaces", headers=hdr, json={"name": "Dup Co", "plan": "starter"})
    assert first.status_code == 201
    dup = client.post("/workspaces", headers=hdr, json={"name": "Dup Co", "plan": "starter"})
    assert dup.status_code == 409
    assert dup.headers.get("access-control-allow-origin") == _ORIGIN
    assert "already exists" in dup.json()["detail"]


def test_duplicate_slug_race_maps_to_409(
    client: TestClient, auth_header: Header, db: Fixtures, monkeypatch
) -> None:
    """If the pre-check misses a concurrent create (simulated), the unique-slug IntegrityError
    is still translated to a 409, not a 500."""
    import api.app.services.workspaces as wss

    hdr = {**auth_header(db.admin_user_id), "Origin": _ORIGIN}
    assert client.post("/workspaces", headers=hdr, json={"name": "Race Co"}).status_code == 201
    # Force the pre-check to miss, so the DB unique constraint is the backstop.
    monkeypatch.setattr(wss, "_slug_taken", lambda slug: False)
    res = client.post("/workspaces", headers=hdr, json={"name": "Race Co"})
    assert res.status_code == 409
    assert res.headers.get("access-control-allow-origin") == _ORIGIN


def test_provisioning_migrates_new_schema_to_head(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    """A freshly provisioned workspace's schema is brought fully to head by upgrade_schema
    (not just partially) — check a late-migration table exists and is tenant-isolated."""
    from sqlalchemy import inspect

    from api.app.db.base import schema_for_workspace
    from api.app.db.session import get_engine

    res = client.post(
        "/workspaces", headers=auth_header(db.admin_user_id), json={"name": "Head Check"}
    )
    assert res.status_code == 201
    schema = schema_for_workspace(res.json()["id"])
    insp = inspect(get_engine())
    tables = set(insp.get_table_names(schema=schema))
    # csam_incidents (0013) + cases (0011) are among the latest tenant migrations.
    assert {"csam_incidents", "cases", "evidence_captures", "audit_log"} <= tables
