"""Slice 5: audit rows on decisions, confirm allowlist re-check, rescore admin gate + audit."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.discovery import CandidateKind, DiscoveryCandidate, ReviewStatus
from api.app.models.public import Workspace
from api.app.models.subjects import AllowlistKind

from .reviewhelpers import add_allowlist, add_candidate, make_subject

Auth = Callable[..., dict[str, str]]


def _actions(schema: str) -> list[str]:
    with tenant_session(schema) as session:
        return list(session.scalars(select(AuditLog.action)).all())


def test_confirm_and_dismiss_and_bulk_are_audited(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    ws, schema = new_workspace.id, new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    confirm_cid = add_candidate(schema, subject_id, source_url="https://a.example/1.jpg")
    dismiss_cid = add_candidate(schema, subject_id, source_url="https://b.example/2.jpg")
    add_candidate(schema, subject_id, source_url="https://bulk.example/3.jpg")

    client.post(
        f"/workspaces/{ws}/review/candidates/{confirm_cid}/confirm",
        headers=hdr, json={"claim_type": "likeness"},
    )
    client.post(
        f"/workspaces/{ws}/review/candidates/{dismiss_cid}/dismiss",
        headers=hdr, json={"reason": "not_a_match"},
    )
    client.post(
        f"/workspaces/{ws}/review/bulk-dismiss",
        headers=hdr, json={"domain": "bulk.example", "reason": "not_a_match", "dry_run": False},
    )

    actions = _actions(schema)
    for expected in ("review.confirm", "case.created", "review.dismiss", "review.bulk_dismiss"):
        assert expected in actions, f"missing audit action {expected}"


def test_reopen_and_rescore_are_audited_and_admin_only(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    ws, schema = new_workspace.id, new_workspace.schema_name
    subject_id = make_subject(schema)
    cid = add_candidate(
        schema, subject_id, source_url="https://x.example/1.jpg",
        review_status=ReviewStatus.dismissed,
    )
    client.post(
        f"/workspaces/{ws}/review/candidates/{cid}/reopen",
        headers=hdr, json={"note": "undo"},
    )
    assert client.post(f"/workspaces/{ws}/review/rescore", headers=hdr, json={}).status_code == 200

    actions = _actions(schema)
    assert "review.reopen" in actions
    assert "review.rescore" in actions


def test_confirm_blocked_for_allowlisted_source(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    """A reopened allowlisted candidate can't be confirmed while the allowlist entry stands."""
    hdr = auth_header("admin_user")
    ws, schema = new_workspace.id, new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    add_allowlist(schema, AllowlistKind.domain, "licensee.example")
    # Pending but on an allowlisted domain (as if reopened).
    cid = add_candidate(
        schema, subject_id, kind=CandidateKind.link,
        source_url="https://licensee.example/x", thumbnail_key=None,
        review_status=ReviewStatus.pending,
    )
    r = client.post(
        f"/workspaces/{ws}/review/candidates/{cid}/confirm",
        headers=hdr, json={"claim_type": "likeness"},
    )
    assert r.status_code == 422
    with tenant_session(schema) as session:
        c = session.get(DiscoveryCandidate, cid)
        assert c is not None and c.review_status == ReviewStatus.pending  # not confirmed
