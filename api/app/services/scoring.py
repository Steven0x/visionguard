"""Candidate scoring + allowlist routing (Slice 5).

Pure-ish scoring (reads the subject's ready assets and workspace allowlist, writes only the
candidate's own review fields). Thresholds, weights and the leak-domain / risky-keyword lists
come from config, never hard-coded. See docs/specs/review.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.config import get_settings
from api.app.models.assets import Asset, AssetStatus
from api.app.models.discovery import DiscoveryCandidate, ReviewStatus
from api.app.models.review import DismissReason, ReviewDecision, ReviewDecisionKind
from api.app.models.subjects import AllowlistEntry, AllowlistKind


@dataclass
class ScoreOutcome:
    score: int
    breakdown: dict
    best_match_asset_id: int | None


def _hamming_hex(a: str, b: str) -> int:
    """Popcount of the XOR of two equal-length hex pHash strings."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _host(url: str | None) -> str:
    if not url:
        return ""
    return (urlsplit(url).hostname or "").lower()


def _matched_keywords(candidate: DiscoveryCandidate) -> list[str]:
    haystack = " ".join(
        p.lower() for p in (candidate.source_url, candidate.page_url, candidate.title) if p
    )
    return [kw for kw in get_settings().review_risky_keyword_list if kw and kw in haystack]


def _ready_assets(session: Session, subject_id: int) -> list[Asset]:
    return list(
        session.scalars(
            select(Asset).where(
                Asset.subject_id == subject_id, Asset.status == AssetStatus.ready
            )
        ).all()
    )


def score_candidate(session: Session, candidate: DiscoveryCandidate) -> ScoreOutcome:
    """Compute a 0–100 score, a component breakdown, and the best-matching ready asset."""
    s = get_settings()
    is_image = candidate.embedding is not None or candidate.phash is not None

    phash_points = 0
    phash_asset: int | None = None
    best_distance: int | None = None
    embed_points = 0
    embed_asset: int | None = None
    best_similarity: float | None = None

    if is_image:
        assets = _ready_assets(session, candidate.subject_id)
        # pHash Hamming distance (exact / near-copy).
        if candidate.phash:
            for asset in assets:
                if not asset.phash:
                    continue
                dist = _hamming_hex(candidate.phash, asset.phash)
                if best_distance is None or dist < best_distance:
                    best_distance, phash_asset = dist, asset.id
            if best_distance is not None:
                if best_distance <= s.review_phash_exact_max:
                    phash_points = s.review_score_visual_exact
                elif best_distance <= s.review_phash_near_max:
                    phash_points = s.review_score_visual_near
                else:
                    phash_asset = None  # too far to claim a match
        # pgvector cosine similarity (crops / edits) — best ready asset.
        if candidate.embedding is not None:
            row = session.execute(
                select(
                    Asset.id,
                    Asset.embedding.cosine_distance(candidate.embedding).label("dist"),
                )
                .where(
                    Asset.subject_id == candidate.subject_id,
                    Asset.status == AssetStatus.ready,
                    Asset.embedding.is_not(None),
                )
                .order_by("dist")
                .limit(1)
            ).first()
            if row is not None:
                best_similarity = 1.0 - float(row.dist)
                if best_similarity >= s.review_embedding_match_threshold:
                    embed_points = min(
                        s.review_score_embedding_max,
                        round(s.review_score_embedding_max * best_similarity),
                    )
                    embed_asset = row.id

    # Rules (apply to every candidate).
    leak_domain = _host(candidate.source_url) in s.review_leak_domain_set or (
        _host(candidate.page_url) in s.review_leak_domain_set
    )
    keywords = _matched_keywords(candidate)
    rule_points = (s.review_score_leak_domain if leak_domain else 0) + min(
        s.review_score_risky_keyword_cap, s.review_score_risky_keyword * len(keywords)
    )

    # Strongest visual signal wins (no double-count); prefer pHash on a tie.
    if phash_points >= embed_points:
        visual_points, best_asset = phash_points, phash_asset
    else:
        visual_points, best_asset = embed_points, embed_asset

    score = min(100, visual_points + rule_points)
    breakdown = {
        "phash": {
            "best_distance": best_distance,
            "asset_id": phash_asset,
            "points": phash_points,
        },
        "embedding": {
            "best_similarity": round(best_similarity, 4) if best_similarity is not None else None,
            "asset_id": embed_asset,
            "points": embed_points,
        },
        "rules": {
            "leak_domain": leak_domain,
            "risky_keywords": keywords,
            "points": rule_points,
        },
        "visual_points": visual_points,
        "unverified": not is_image,  # link candidates can't be visually verified
    }
    return ScoreOutcome(score=score, breakdown=breakdown, best_match_asset_id=best_asset)


# ── Allowlist ─────────────────────────────────────────────────────────────────


def is_allowlisted(session: Session, candidate: DiscoveryCandidate) -> bool:
    """True if the candidate's source/page URL matches any workspace allowlist entry."""
    urls = [u.lower() for u in (candidate.source_url, candidate.page_url) if u]
    hosts = {_host(candidate.source_url), _host(candidate.page_url)} - {""}
    for entry in session.scalars(select(AllowlistEntry)).all():
        value = entry.value.strip().lower()
        if not value:
            continue
        if entry.kind == AllowlistKind.domain:
            if any(h == value or h.endswith(f".{value}") for h in hosts):
                return True
        elif entry.kind == AllowlistKind.url:
            if any(u == value or u.startswith(value) for u in urls):
                return True
        elif entry.kind in (AllowlistKind.handle, AllowlistKind.account):
            needle = value.lstrip("@")
            if needle and any(needle in u for u in urls):
                return True
    return False


# ── Persisting scoring + allowlist routing ────────────────────────────────────


def apply_scoring(session: Session, candidate: DiscoveryCandidate) -> None:
    """Score a candidate and route it: allowlisted → auto_dismissed (system decision), else
    pending. Records a system ReviewDecision only on the *transition into* auto_dismissed, so
    repeated rescores of a still-allowlisted candidate don't duplicate its training label.
    Flushes."""
    was_auto_dismissed = candidate.review_status == ReviewStatus.auto_dismissed
    outcome = score_candidate(session, candidate)
    candidate.score = outcome.score
    candidate.score_breakdown = outcome.breakdown
    candidate.best_match_asset_id = outcome.best_match_asset_id
    if is_allowlisted(session, candidate):
        candidate.review_status = ReviewStatus.auto_dismissed
        candidate.dismiss_reason = DismissReason.allowlisted
        if not was_auto_dismissed:
            session.add(
                ReviewDecision(
                    candidate_id=candidate.id,
                    subject_id=candidate.subject_id,
                    decision=ReviewDecisionKind.dismiss,
                    reason=DismissReason.allowlisted,
                    score=outcome.score,
                    decided_by_staff_id=None,  # system
                )
            )
    else:
        candidate.review_status = ReviewStatus.pending
        candidate.dismiss_reason = None
    session.flush()


@dataclass
class RescoreResult:
    rescored: int = 0
    changed: list[int] = field(default_factory=list)


def rescore_candidates(
    session: Session, *, subject_id: int | None = None
) -> RescoreResult:
    """Re-score pending / auto_dismissed candidates and re-apply the allowlist. Human
    confirmed/dismissed decisions are never touched. Returns how many were re-scored."""
    stmt = select(DiscoveryCandidate).where(
        DiscoveryCandidate.review_status.in_(
            [ReviewStatus.pending, ReviewStatus.auto_dismissed]
        )
    )
    if subject_id is not None:
        stmt = stmt.where(DiscoveryCandidate.subject_id == subject_id)
    result = RescoreResult()
    for candidate in session.scalars(stmt).all():
        before = candidate.review_status
        apply_scoring(session, candidate)
        result.rescored += 1
        if candidate.review_status != before:
            result.changed.append(candidate.id)
    return result
