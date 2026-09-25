"""Slice 5 scoring: pHash exact/near, embedding similarity, rules, link-only + unverified."""

from __future__ import annotations

from api.app.db.session import tenant_session
from api.app.models.discovery import CandidateKind, DiscoveryCandidate, ReviewStatus
from api.app.models.public import Workspace
from api.app.services.scoring import apply_scoring, score_candidate

from .reviewhelpers import add_asset, add_candidate, make_subject


def _score(schema: str, candidate_id: int) -> DiscoveryCandidate:
    with tenant_session(schema) as session:
        candidate = session.get(DiscoveryCandidate, candidate_id)
        assert candidate is not None
        outcome = score_candidate(session, candidate)
        candidate.score = outcome.score
        candidate.score_breakdown = outcome.breakdown
        candidate.best_match_asset_id = outcome.best_match_asset_id
        session.flush()
        session.refresh(candidate)
        session.expunge(candidate)
        assert candidate.score_breakdown is not None
        return candidate


def test_phash_exact_copy_scores_high_with_best_asset(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    asset_id = add_asset(schema, subject_id, phash="ffffffffffffffff")
    cid = add_candidate(schema, subject_id, phash="ffffffffffffffff")

    c = _score(schema, cid)
    bd = c.score_breakdown
    assert bd is not None
    assert c.score is not None and c.score >= 60
    assert c.best_match_asset_id == asset_id
    assert bd["phash"]["best_distance"] == 0
    assert bd["unverified"] is False


def test_phash_far_is_not_a_match(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    add_asset(schema, subject_id, phash="0000000000000000")
    cid = add_candidate(schema, subject_id, phash="ffffffffffffffff")  # distance 64

    c = _score(schema, cid)
    bd = c.score_breakdown
    assert bd is not None
    assert bd["phash"]["points"] == 0
    assert c.best_match_asset_id is None


def test_embedding_similarity_matches_crop(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    asset_id = add_asset(schema, subject_id, embed=0.5)
    cid = add_candidate(schema, subject_id, embed=0.5)  # identical vector → cosine sim 1.0

    c = _score(schema, cid)
    bd = c.score_breakdown
    assert bd is not None
    assert bd["embedding"]["points"] > 0
    assert bd["embedding"]["best_similarity"] >= 0.99
    assert c.best_match_asset_id == asset_id


def test_leak_domain_and_keyword_rules(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    cid = add_candidate(
        schema,
        subject_id,
        kind=CandidateKind.link,
        source_url="https://leaks.example/leaked/free-photos",
        thumbnail_key=None,
    )
    c = _score(schema, cid)
    bd = c.score_breakdown
    assert bd is not None
    assert bd["rules"]["leak_domain"] is True
    assert "leaked" in bd["rules"]["risky_keywords"]
    assert bd["rules"]["points"] > 0


def test_link_candidate_is_rules_only_and_unverified(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    add_asset(schema, subject_id, phash="ffffffffffffffff", embed=0.5)
    cid = add_candidate(
        schema,
        subject_id,
        kind=CandidateKind.link,
        source_url="https://ordinary.example/page",
        thumbnail_key=None,
    )
    c = _score(schema, cid)
    bd = c.score_breakdown
    assert bd is not None
    assert bd["unverified"] is True
    assert bd["phash"]["points"] == 0
    assert bd["embedding"]["points"] == 0
    assert c.score == bd["rules"]["points"]


def test_apply_scoring_routes_ordinary_candidate_to_pending(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    cid = add_candidate(
        schema, subject_id, kind=CandidateKind.link,
        source_url="https://ordinary.example/x", thumbnail_key=None,
        review_status=ReviewStatus.pending,
    )
    with tenant_session(schema) as session:
        candidate = session.get(DiscoveryCandidate, cid)
        assert candidate is not None
        apply_scoring(session, candidate)
        assert candidate.review_status == ReviewStatus.pending
