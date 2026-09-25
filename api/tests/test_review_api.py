"""Slice 5 API: inbox filters + suggested claim, confirm/dismiss/reopen, race → 409."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryCandidate, ReviewStatus
from api.app.models.public import Workspace
from api.app.models.review import Case, ReviewDecision, ReviewDecisionKind

from .reviewhelpers import add_candidate, make_subject

Auth = Callable[..., dict[str, str]]


def _inbox(client: TestClient, ws: int, hdr: dict[str, str], **params: object) -> list[dict]:
    r = client.get(f"/workspaces/{ws}/review/inbox", headers=hdr, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_inbox_lists_pending_only_with_suggested_claim(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)  # likeness supported
    pending = add_candidate(schema, subject_id, source_url="https://a.example/1.jpg", score=80)
    add_candidate(
        schema, subject_id, source_url="https://b.example/2.jpg",
        review_status=ReviewStatus.auto_dismissed, score=10,
    )

    items = _inbox(client, new_workspace.id, hdr)
    ids = [i["id"] for i in items]
    assert pending in ids
    assert len(items) == 1  # auto_dismissed hidden
    assert items[0]["suggested_claim"] == "likeness"
    assert "likeness" in items[0]["supported_claims"]


def test_inbox_not_supported_when_no_claim(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)  # authorized but no rights/consent → nothing supported
    add_candidate(schema, subject_id, source_url="https://a.example/1.jpg")
    items = _inbox(client, new_workspace.id, auth_header("admin_user"))
    assert items[0]["suggested_claim"] is None
    assert items[0]["supported_claims"] == []


def test_inbox_filters_by_min_score_and_domain(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    add_candidate(schema, subject_id, source_url="https://hi.example/a.jpg", score=90)
    add_candidate(schema, subject_id, source_url="https://lo.example/b.jpg", score=5)

    high = _inbox(client, new_workspace.id, hdr, min_score=50)
    assert [i["source_url"] for i in high] == ["https://hi.example/a.jpg"]
    dom = _inbox(client, new_workspace.id, hdr, domain="lo.example")
    assert [i["source_url"] for i in dom] == ["https://lo.example/b.jpg"]


def test_confirm_creates_case_and_labeled_decision(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    cid = add_candidate(schema, subject_id, source_url="https://x.example/1.jpg")

    r = client.post(
        f"/workspaces/{new_workspace.id}/review/candidates/{cid}/confirm",
        headers=hdr, json={"claim_type": "likeness"},
    )
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]

    with tenant_session(schema) as session:
        confirmed = session.get(DiscoveryCandidate, cid)
        assert confirmed is not None and confirmed.review_status == ReviewStatus.confirmed
        case = session.get(Case, case_id)
        assert case is not None and case.candidate_id == cid and case.claim_type == "likeness"
        decision = session.scalar(
            select(ReviewDecision).where(
                ReviewDecision.candidate_id == cid,
                ReviewDecision.decision == ReviewDecisionKind.confirm,
            )
        )
        assert decision is not None and decision.decided_by_staff_id is not None


def test_confirm_rejects_unsupported_claim(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)  # likeness only
    cid = add_candidate(schema, subject_id, source_url="https://x.example/1.jpg")
    r = client.post(
        f"/workspaces/{new_workspace.id}/review/candidates/{cid}/confirm",
        headers=auth_header("admin_user"), json={"claim_type": "copyright"},
    )
    assert r.status_code == 422


def test_confirm_rechecks_enforceability(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, authorized=False)
    cid = add_candidate(schema, subject_id, source_url="https://x.example/1.jpg")
    r = client.post(
        f"/workspaces/{new_workspace.id}/review/candidates/{cid}/confirm",
        headers=auth_header("admin_user"), json={"claim_type": "likeness"},
    )
    assert r.status_code == 403


def test_no_double_confirm(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    cid = add_candidate(schema, subject_id, source_url="https://x.example/1.jpg")
    url = f"/workspaces/{new_workspace.id}/review/candidates/{cid}/confirm"
    first = client.post(url, headers=hdr, json={"claim_type": "likeness"})
    second = client.post(url, headers=hdr, json={"claim_type": "likeness"})
    assert first.status_code == 201
    assert second.status_code == 409  # lost the race — no second case
    with tenant_session(schema) as session:
        assert len(session.scalars(select(Case)).all()) == 1


def test_dismiss_stores_reason_and_rejects_allowlisted(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    cid = add_candidate(schema, subject_id, source_url="https://x.example/1.jpg")
    base = f"/workspaces/{new_workspace.id}/review/candidates/{cid}/dismiss"

    # Humans can't pick 'allowlisted'.
    assert client.post(base, headers=hdr, json={"reason": "allowlisted"}).status_code == 422

    ok = client.post(base, headers=hdr, json={"reason": "not_a_match"})
    assert ok.status_code == 204
    with tenant_session(schema) as session:
        c = session.get(DiscoveryCandidate, cid)
        assert c is not None
        assert c.review_status == ReviewStatus.dismissed and c.dismiss_reason == "not_a_match"

    # Already decided → 409.
    assert client.post(base, headers=hdr, json={"reason": "licensed"}).status_code == 409


def test_reopen_returns_dismissed_to_pending(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    cid = add_candidate(
        schema, subject_id, source_url="https://x.example/1.jpg",
        review_status=ReviewStatus.dismissed,
    )
    reopen = f"/workspaces/{new_workspace.id}/review/candidates/{cid}/reopen"
    assert client.post(reopen, headers=hdr, json={"note": ""}).status_code == 422  # note required
    assert client.post(reopen, headers=hdr, json={"note": "mistaken dismissal"}).status_code == 204
    with tenant_session(schema) as session:
        reopened = session.get(DiscoveryCandidate, cid)
        assert reopened is not None and reopened.review_status == ReviewStatus.pending
        decision = session.scalar(
            select(ReviewDecision).where(
                ReviewDecision.candidate_id == cid,
                ReviewDecision.decision == ReviewDecisionKind.reopen,
            )
        )
        assert decision is not None and decision.note == "mistaken dismissal"


def test_reopen_is_admin_only(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    # A throwaway reviewer WITH access to this workspace, so the 403 comes from the ADMIN role
    # gate — not from require_workspace_access (and without polluting the shared reviewer_a).
    import uuid

    from api.app.models.public import StaffRole
    from api.app.services.staff import create_staff, grant_workspace_access

    clerk_id = f"reviewer_{uuid.uuid4().hex[:8]}"
    reviewer = create_staff(
        clerk_user_id=clerk_id, email=f"{clerk_id}@vg.test", role=StaffRole.reviewer
    )
    grant_workspace_access(staff_id=reviewer.id, workspace_id=new_workspace.id)
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    cid = add_candidate(
        schema, subject_id, review_status=ReviewStatus.dismissed,
        source_url="https://x.example/1.jpg",
    )
    # Reviewer can see the inbox (has access) but cannot reopen (needs admin).
    assert client.get(
        f"/workspaces/{new_workspace.id}/review/inbox", headers=auth_header(clerk_id)
    ).status_code == 200
    r = client.post(
        f"/workspaces/{new_workspace.id}/review/candidates/{cid}/reopen",
        headers=auth_header(clerk_id), json={"note": "n"},
    )
    assert r.status_code == 403
