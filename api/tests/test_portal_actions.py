"""Agency write actions (Slice 12): a URL tip becomes a pending candidate (never auto-confirmed),
the per-user daily tip cap returns 429, and a staff member can see + review submissions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryCandidate, ReviewStatus
from api.app.models.public import Workspace
from api.tests.portalhelpers import make_agency_user
from api.tests.reviewhelpers import make_subject


def _agency(client: TestClient, ws: Workspace, auth_header, uid: str = "agency_act"):
    make_agency_user(clerk_user_id=uid, email=f"{uid}@agency.test", workspace_id=ws.id)
    return auth_header(uid)


def test_tip_creates_a_pending_candidate(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema, authorized=True)  # enforceable → intake proceeds
    hdr = _agency(client, new_workspace, auth_header, uid="agency_tip_ok")
    resp = client.post(
        "/portal/tips", headers=hdr, json={"subject_id": sid, "url": "https://tip.example/x"}
    )
    assert resp.status_code == 201 and resp.json()["candidate_created"] is True
    with tenant_session(schema) as session:
        cands = list(session.scalars(select(DiscoveryCandidate)))
        assert len(cands) == 1
        # Never auto-confirmed — lands in the staff review inbox as pending.
        assert cands[0].review_status == ReviewStatus.pending
        assert cands[0].provider == "manual"


def test_tip_for_unenforceable_subject_is_recorded_not_dropped(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema, authorized=False)  # not enforceable
    hdr = _agency(client, new_workspace, auth_header, uid="agency_tip_unauth")
    resp = client.post(
        "/portal/tips", headers=hdr, json={"subject_id": sid, "url": "https://tip.example/y"}
    )
    assert resp.status_code == 201 and resp.json()["candidate_created"] is False


def test_daily_tip_cap_returns_429(
    client: TestClient, new_workspace: Workspace, auth_header, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema, authorized=True)
    hdr = _agency(client, new_workspace, auth_header, uid="agency_cap")
    monkeypatch.setattr(get_settings(), "portal_tip_daily_cap", 2)
    codes = [
        client.post(
            "/portal/tips", headers=hdr, json={"subject_id": sid, "url": f"https://t.example/{i}"}
        ).status_code
        for i in range(3)
    ]
    assert codes[:2] == [201, 201]
    assert codes[2] == 429


def test_staff_can_list_and_review_submissions(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema, authorized=True)
    hdr = _agency(client, new_workspace, auth_header, uid="agency_rev")
    client.post("/portal/tips", headers=hdr, json={"subject_id": sid, "url": "https://t.example/z"})

    admin = auth_header("admin_user")
    rows = client.get(f"/workspaces/{new_workspace.id}/submissions", headers=admin).json()
    assert len(rows) == 1 and rows[0]["kind"] == "url_tip"
    sub_id = rows[0]["id"]
    reviewed = client.post(
        f"/workspaces/{new_workspace.id}/submissions/{sub_id}/review",
        headers=admin,
        json={"status": "reviewed"},
    )
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "reviewed"


def test_needs_answer_text_only(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    sid = make_subject(new_workspace.schema_name)
    hdr = _agency(client, new_workspace, auth_header, uid="agency_txt")
    resp = client.post(
        "/portal/needs/answer",
        headers=hdr,
        data={"subject_id": str(sid), "need_type": "missing_authorization", "body": "we have it"},
    )
    assert resp.status_code == 201


def test_needs_answer_requires_text_or_file(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    sid = make_subject(new_workspace.schema_name)
    hdr = _agency(client, new_workspace, auth_header, uid="agency_empty")
    resp = client.post(
        "/portal/needs/answer",
        headers=hdr,
        data={"subject_id": str(sid), "need_type": "missing_authorization"},
    )
    assert resp.status_code == 422


def test_needs_answer_rejects_unknown_need_type(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    sid = make_subject(new_workspace.schema_name)
    hdr = _agency(client, new_workspace, auth_header, uid="agency_badneed")
    resp = client.post(
        "/portal/needs/answer",
        headers=hdr,
        data={"subject_id": str(sid), "need_type": "'; drop", "body": "x"},
    )
    assert resp.status_code == 422
