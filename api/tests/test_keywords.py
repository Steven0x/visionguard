"""Subject keyword identifiers: normalize, dedupe, remove, audit, identifiers union."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.public import Workspace
from api.tests.conftest import Fixtures


def _subject(client, auth_header, db, ws: Workspace) -> int:
    return client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Kw", "stage_names": ["Star"], "handles": ["@Jane"]},
    ).json()["id"]


def test_add_normalizes_and_dedupes(client: TestClient, auth_header, db: Fixtures, new_workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    base = f"/workspaces/{new_workspace.id}/subjects/{sid}/keywords"
    hdr = auth_header(db.admin_user_id)

    first = client.post(base, headers=hdr, json={"keyword": "  Leaked   Photos "})
    assert first.status_code == 201
    assert first.json()["keyword"] == "leaked photos"

    # Same value after normalization → idempotent (deduped by unique constraint).
    again = client.post(base, headers=hdr, json={"keyword": "leaked photos"})
    assert again.json()["id"] == first.json()["id"]

    listed = client.get(base, headers=hdr).json()
    assert [k["keyword"] for k in listed] == ["leaked photos"]


def test_remove_and_audit(client: TestClient, auth_header, db: Fixtures, new_workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    base = f"/workspaces/{new_workspace.id}/subjects/{sid}/keywords"
    hdr = auth_header(db.admin_user_id)
    kid = client.post(base, headers=hdr, json={"keyword": "vip"}).json()["id"]
    assert client.delete(f"{base}/{kid}", headers=hdr).status_code == 204

    with tenant_session(new_workspace.schema_name) as s:
        actions = set(s.scalars(select(AuditLog.action)).all())
    assert {"keyword.added", "keyword.removed"} <= actions


def test_identifiers_union(client: TestClient, auth_header, db: Fixtures, new_workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    base = f"/workspaces/{new_workspace.id}/subjects/{sid}"
    hdr = auth_header(db.admin_user_id)
    client.post(f"{base}/keywords", headers=hdr, json={"keyword": "leaked"})

    identifiers = client.get(f"{base}/identifiers", headers=hdr).json()["identifiers"]
    assert "Star" in identifiers  # stage name
    assert "jane" in identifiers  # normalized handle (Slice 1)
    assert "leaked" in identifiers  # keyword
