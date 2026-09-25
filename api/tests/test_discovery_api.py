"""Discovery API: scan endpoint, candidate thumbnail, access, audit, settings."""

from __future__ import annotations

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.discovery import CandidateKind, DiscoveryCandidate
from api.tests.discohelpers import authorized_subject


def test_scan_endpoint_produces_candidates_and_audits(client, auth_header, db, new_workspace):
    sid, _ = authorized_subject(
        new_workspace.schema_name, ready_asset=True, keywords=("leaked",)
    )
    hdr = auth_header(db.admin_user_id)
    res = client.post(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/discovery/scan", headers=hdr
    )
    assert res.status_code == 200
    assert res.json()["enqueued"] >= 2  # one reverse (ready asset) + one keyword

    candidates = client.get(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/discovery/candidates", headers=hdr
    ).json()
    assert candidates
    assert not any("thumbnail_key" in c or "embedding" in c for c in candidates)

    with tenant_session(new_workspace.schema_name) as s:
        assert "discovery.scan_run" in set(s.scalars(select(AuditLog.action)).all())
        image = s.scalar(
            select(DiscoveryCandidate).where(DiscoveryCandidate.kind == CandidateKind.image)
        )
        image_id = image.id

    dl = client.get(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/discovery/candidates/{image_id}/thumbnail",
        headers=hdr,
    )
    assert dl.status_code == 200
    assert dl.json()["url"].startswith("http")


def test_reviewer_without_access_is_forbidden(client, auth_header, db, new_workspace):
    sid, _ = authorized_subject(new_workspace.schema_name)
    res = client.get(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/discovery/candidates",
        headers=auth_header(db.reviewer_a_user_id),  # no access to new_workspace
    )
    assert res.status_code == 403


def test_settings_get_and_admin_only_update(client, auth_header, db, new_workspace):
    base = f"/workspaces/{new_workspace.id}/discovery/settings"
    assert client.get(base, headers=auth_header(db.admin_user_id)).status_code == 200

    # reviewer_a has no access to this workspace → 403 regardless of role.
    denied = client.put(
        base, headers=auth_header(db.reviewer_a_user_id), json={"scan_frequency": "daily"}
    )
    assert denied.status_code == 403

    ok = client.put(
        base,
        headers=auth_header(db.admin_user_id),
        json={"scan_frequency": "daily", "tineye_enabled": True, "monthly_call_budget": 42},
    )
    assert ok.status_code == 200
    assert ok.json()["scan_frequency"] == "daily"
    assert ok.json()["monthly_call_budget"] == 42
