"""Access control + audit policy for assets (thumbnail not audited, original audited)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.public import Workspace
from api.tests.conftest import Fixtures
from api.tests.imgutil import png_bytes


def _subject(client, auth_header, db, ws: Workspace) -> int:
    return client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "S"},
    ).json()["id"]


def _upload(client, auth_header, db, ws, sid) -> int:
    return client.post(
        f"/workspaces/{ws.id}/subjects/{sid}/assets",
        headers=auth_header(db.admin_user_id),
        files={"file": ("p.png", png_bytes(), "application/octet-stream")},
    ).json()["id"]


def _actions(schema: str) -> list[str]:
    with tenant_session(schema) as s:
        return list(s.scalars(select(AuditLog.action)).all())


def test_reviewer_without_access_is_forbidden(
    client: TestClient, auth_header, db: Fixtures, new_workspace
):
    sid = _subject(client, auth_header, db, new_workspace)
    aid = _upload(client, auth_header, db, new_workspace, sid)
    hdr = auth_header(db.reviewer_a_user_id)  # no access to new_workspace
    base = f"/workspaces/{new_workspace.id}/subjects/{sid}"
    assert client.get(f"{base}/assets", headers=hdr).status_code == 403
    assert client.get(f"{base}/assets/{aid}/thumbnail", headers=hdr).status_code == 403
    assert client.get(f"{base}/assets/{aid}/original", headers=hdr).status_code == 403


def test_thumbnail_not_audited_original_audited(
    client: TestClient, auth_header, db: Fixtures, new_workspace
):
    sid = _subject(client, auth_header, db, new_workspace)
    aid = _upload(client, auth_header, db, new_workspace, sid)
    hdr = auth_header(db.admin_user_id)
    base = f"/workspaces/{new_workspace.id}/subjects/{sid}/assets/{aid}"

    assert client.get(f"{base}/thumbnail", headers=hdr).status_code == 200
    assert "document.downloaded" not in _actions(new_workspace.schema_name)

    assert client.get(f"{base}/original", headers=hdr).status_code == 200
    assert "document.downloaded" in _actions(new_workspace.schema_name)


def test_upload_and_delete_are_audited(
    client: TestClient, auth_header, db: Fixtures, new_workspace
):
    sid = _subject(client, auth_header, db, new_workspace)
    aid = _upload(client, auth_header, db, new_workspace, sid)
    hdr = auth_header(db.admin_user_id)
    assert client.delete(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/assets/{aid}", headers=hdr
    ).status_code == 204
    actions = _actions(new_workspace.schema_name)
    assert "asset.uploaded" in actions
    assert "asset.deleted" in actions
