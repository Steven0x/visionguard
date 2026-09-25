"""Authorization gate: no discovery (intake or scan) without an active authorization."""

from __future__ import annotations

from sqlalchemy import select
from worker.discovery import reverse_image_scan

from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryRun, RunStatus
from api.tests.discohelpers import unauthorized_subject


def test_intake_forbidden_for_unauthorized(client, auth_header, db, new_workspace):
    sid, _ = unauthorized_subject(new_workspace.schema_name)
    res = client.post(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/discovery/intake",
        headers=auth_header(db.admin_user_id),
        json={"urls": ["https://x.example/a"]},
    )
    assert res.status_code == 403


def test_scan_endpoint_forbidden_for_unauthorized(client, auth_header, db, new_workspace):
    sid, _ = unauthorized_subject(new_workspace.schema_name)
    res = client.post(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/discovery/scan",
        headers=auth_header(db.admin_user_id),
    )
    assert res.status_code == 403


def test_reverse_scan_task_blocks_and_makes_no_calls(db, new_workspace):
    sid, aid = unauthorized_subject(new_workspace.schema_name, ready_asset=True)
    assert reverse_image_scan.run(new_workspace.id, sid, aid) == "blocked"
    with tenant_session(new_workspace.schema_name) as s:
        run = s.scalar(select(DiscoveryRun).order_by(DiscoveryRun.id.desc()))
        assert run is not None
        assert run.status == RunStatus.blocked
        assert run.calls_made == 0
