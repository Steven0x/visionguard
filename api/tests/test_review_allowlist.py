"""Slice 5: allowlisted candidates are auto-dismissed before the inbox; rescore re-applies."""

from __future__ import annotations

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.discovery import CandidateKind, DiscoveryCandidate, ReviewStatus
from api.app.models.public import Workspace
from api.app.models.review import DismissReason, ReviewDecision
from api.app.models.subjects import AllowlistEntry, AllowlistKind
from api.app.services.scoring import apply_scoring, rescore_candidates

from .reviewhelpers import add_allowlist, add_candidate, make_subject


def _apply(schema: str, candidate_id: int) -> DiscoveryCandidate:
    with tenant_session(schema) as session:
        candidate = session.get(DiscoveryCandidate, candidate_id)
        assert candidate is not None
        apply_scoring(session, candidate)
        session.refresh(candidate)
        session.expunge(candidate)
        return candidate


def test_allowlisted_domain_auto_dismissed_with_system_decision(
    new_workspace: Workspace,
) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    add_allowlist(schema, AllowlistKind.domain, "licensee.example")
    cid = add_candidate(
        schema, subject_id, kind=CandidateKind.link,
        source_url="https://licensee.example/gallery", thumbnail_key=None,
    )
    c = _apply(schema, cid)
    assert c.review_status == ReviewStatus.auto_dismissed
    assert c.dismiss_reason == DismissReason.allowlisted

    with tenant_session(schema) as session:
        decision = session.scalar(
            select(ReviewDecision).where(ReviewDecision.candidate_id == cid)
        )
        assert decision is not None
        assert decision.reason == DismissReason.allowlisted
        assert decision.decided_by_staff_id is None  # system decision


def test_rescore_reapplies_allowlist_both_directions(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    cid = add_candidate(
        schema, subject_id, kind=CandidateKind.link,
        source_url="https://maybe.example/x", thumbnail_key=None,
    )
    _apply(schema, cid)  # pending (not allowlisted yet)

    # Add an allowlist entry, then rescore → auto-dismissed.
    add_allowlist(schema, AllowlistKind.domain, "maybe.example")
    with tenant_session(schema) as session:
        rescore_candidates(session)
    with tenant_session(schema) as session:
        c = session.get(DiscoveryCandidate, cid)
        assert c is not None and c.review_status == ReviewStatus.auto_dismissed

    # Remove the entry, then rescore → back to pending.
    with tenant_session(schema) as session:
        for e in session.scalars(select(AllowlistEntry)).all():
            session.delete(e)
    with tenant_session(schema) as session:
        rescore_candidates(session)
    with tenant_session(schema) as session:
        c = session.get(DiscoveryCandidate, cid)
        assert c is not None and c.review_status == ReviewStatus.pending


def test_rescore_does_not_duplicate_system_decision(new_workspace: Workspace) -> None:
    """Repeated rescores of a still-allowlisted candidate must not duplicate its training
    label (review_decisions is the corpus)."""
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    add_allowlist(schema, AllowlistKind.domain, "licensee.example")
    cid = add_candidate(
        schema, subject_id, kind=CandidateKind.link,
        source_url="https://licensee.example/x", thumbnail_key=None,
    )
    _apply(schema, cid)  # one system decision on the transition into auto_dismissed
    with tenant_session(schema) as session:
        rescore_candidates(session)
        rescore_candidates(session)
    with tenant_session(schema) as session:
        decisions = session.scalars(
            select(ReviewDecision).where(ReviewDecision.candidate_id == cid)
        ).all()
        assert len(decisions) == 1
