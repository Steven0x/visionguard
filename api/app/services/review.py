"""Review-inbox services (Slice 5): listing, confirm, dismiss, reopen, bulk, cases, guards.

Confirm/dismiss use a conditional UPDATE (``WHERE review_status='pending'``) so two reviewers
acting on the same candidate can't both win — the loser gets a 409. Confirm re-checks
enforceability and claim support at confirm time, not what the inbox showed earlier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.models.discovery import DiscoveryCandidate, ReviewStatus
from api.app.models.review import (
    Case,
    CaseStatus,
    DismissReason,
    ReviewDecision,
    ReviewDecisionKind,
)
from api.app.models.subjects import Subject
from api.app.services.claim_support import claim_support, subject_enforcement
from api.app.services.scoring import is_allowlisted

# Which claim to suggest first when several are supported.
_CLAIM_PRIORITY = ("copyright", "likeness", "ncii", "impersonation", "trademark")


class ReviewConflict(Exception):
    """The candidate was already decided by someone else (lost the race) → 409."""


class NotEnforceable(Exception):
    """Confirm attempted for a subject without an active authorization → 403."""


class ClaimNotSupported(Exception):
    """Chosen claim type isn't currently supported by the subject's records → 422."""


class InvalidReason(Exception):
    """A dismiss reason that a human may not pick (e.g. allowlisted) → 422."""


class CandidateAllowlisted(Exception):
    """Confirm attempted on a source that currently matches the allowlist → 422."""


def _host(url: str | None) -> str:
    if not url:
        return ""
    return (urlsplit(url).hostname or "").lower()


def supported_claims(session: Session, subject: Subject) -> list[str]:
    return [c.claim_type for c in claim_support(session, subject) if c.supported]


def suggested_claim(session: Session, subject: Subject) -> str | None:
    supported = set(supported_claims(session, subject))
    return next((c for c in _CLAIM_PRIORITY if c in supported), None)


# ── Inbox listing ─────────────────────────────────────────────────────────────


@dataclass
class InboxItem:
    candidate: DiscoveryCandidate
    subject: Subject
    suggested_claim: str | None
    supported_claims: list[str]


def list_inbox(
    session: Session,
    *,
    subject_id: int | None = None,
    min_score: int | None = None,
    provider: str | None = None,
    domain: str | None = None,
    kind: str | None = None,
) -> list[InboxItem]:
    stmt = select(DiscoveryCandidate).where(
        DiscoveryCandidate.review_status == ReviewStatus.pending
    )
    if subject_id is not None:
        stmt = stmt.where(DiscoveryCandidate.subject_id == subject_id)
    if min_score is not None:
        stmt = stmt.where(DiscoveryCandidate.score >= min_score)
    if provider is not None:
        stmt = stmt.where(DiscoveryCandidate.provider == provider)
    if kind is not None:
        stmt = stmt.where(DiscoveryCandidate.kind == kind)
    stmt = stmt.order_by(
        DiscoveryCandidate.score.desc().nullslast(), DiscoveryCandidate.id.desc()
    )
    candidates = list(session.scalars(stmt).all())
    if domain is not None:
        d = domain.strip().lower()
        candidates = [
            c
            for c in candidates
            if _host(c.source_url) == d
            or _host(c.source_url).endswith(f".{d}")
            or _host(c.page_url) == d
        ]

    # Batch-load subjects + cache per-subject claim support.
    subject_ids = {c.subject_id for c in candidates}
    subjects = {
        s.id: s
        for s in session.scalars(select(Subject).where(Subject.id.in_(subject_ids))).all()
    }
    claim_cache: dict[int, tuple[str | None, list[str]]] = {}
    items: list[InboxItem] = []
    for c in candidates:
        subject = subjects.get(c.subject_id)
        if subject is None:  # pragma: no cover - FK guarantees presence
            continue
        if subject.id not in claim_cache:
            sup = supported_claims(session, subject)
            claim_cache[subject.id] = (
                next((ct for ct in _CLAIM_PRIORITY if ct in set(sup)), None),
                sup,
            )
        suggested, sup = claim_cache[subject.id]
        items.append(
            InboxItem(
                candidate=c,
                subject=subject,
                suggested_claim=suggested,
                supported_claims=sup,
            )
        )
    return items


def get_candidate(session: Session, candidate_id: int) -> DiscoveryCandidate | None:
    return session.get(DiscoveryCandidate, candidate_id)


def list_cases(session: Session) -> list[Case]:
    return list(session.scalars(select(Case).order_by(Case.id.desc())).all())


# ── Decisions ─────────────────────────────────────────────────────────────────


def _claim_pending(session: Session, candidate_id: int, new_status: ReviewStatus) -> bool:
    """Atomically flip a candidate pending → new_status. False if it wasn't pending."""
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(DiscoveryCandidate)
            .where(
                DiscoveryCandidate.id == candidate_id,
                DiscoveryCandidate.review_status == ReviewStatus.pending,
            )
            .values(review_status=new_status)
        ),
    )
    return result.rowcount == 1


def confirm_candidate(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    subject: Subject,
    candidate: DiscoveryCandidate,
    claim_type: str,
) -> Case:
    # Re-check enforceability + claim support at confirm time (not what the inbox showed).
    if not subject_enforcement(session, subject)["enforceable"]:
        raise NotEnforceable("subject has no active agent authorization")
    if claim_type not in set(supported_claims(session, subject)):
        raise ClaimNotSupported(f"claim '{claim_type}' is not supported for this subject")
    # Allowlist first (CLAUDE.md #8): a reopened/allowlisted source can't reach a case without
    # an explicit allowlist edit, even if a reviewer tries to confirm it.
    if is_allowlisted(session, candidate):
        raise CandidateAllowlisted("source is on the workspace allowlist; remove it first")

    if not _claim_pending(session, candidate.id, ReviewStatus.confirmed):
        raise ReviewConflict("candidate is no longer pending")
    session.refresh(candidate)
    candidate.matched_at = datetime.now(UTC)

    case = Case(
        subject_id=subject.id,
        candidate_id=candidate.id,
        matched_asset_id=candidate.best_match_asset_id,
        claim_type=claim_type,
        status=CaseStatus.confirmed,
        opened_by_staff_id=actor_staff_id,
    )
    session.add(case)
    session.flush()
    session.add(
        ReviewDecision(
            candidate_id=candidate.id,
            subject_id=subject.id,
            decision=ReviewDecisionKind.confirm,
            claim_type=claim_type,
            score=candidate.score,
            decided_by_staff_id=actor_staff_id,
        )
    )
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="review.confirm",
        entity_type="discovery_candidate",
        entity_id=str(candidate.id),
        meta={"claim_type": claim_type, "case_id": case.id},
    )
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="case.created",
        entity_type="case",
        entity_id=str(case.id),
        meta={"claim_type": claim_type, "subject_id": subject.id},
    )
    return case


def dismiss_candidate(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    candidate: DiscoveryCandidate,
    reason: str,
) -> None:
    if reason == DismissReason.allowlisted:
        raise InvalidReason("'allowlisted' is system-only and can't be chosen by a reviewer")
    if not _claim_pending(session, candidate.id, ReviewStatus.dismissed):
        raise ReviewConflict("candidate is no longer pending")
    session.refresh(candidate)
    candidate.dismiss_reason = reason
    session.add(
        ReviewDecision(
            candidate_id=candidate.id,
            subject_id=candidate.subject_id,
            decision=ReviewDecisionKind.dismiss,
            reason=reason,
            score=candidate.score,
            decided_by_staff_id=actor_staff_id,
        )
    )
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="review.dismiss",
        entity_type="discovery_candidate",
        entity_id=str(candidate.id),
        meta={"reason": reason},
    )


def reopen_candidate(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    candidate: DiscoveryCandidate,
    note: str,
) -> None:
    """Return a dismissed / auto_dismissed candidate to pending (admin, required note)."""
    if not note.strip():
        raise InvalidReason("a note is required to reopen a candidate")
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(DiscoveryCandidate)
            .where(
                DiscoveryCandidate.id == candidate.id,
                DiscoveryCandidate.review_status.in_(
                    [ReviewStatus.dismissed, ReviewStatus.auto_dismissed]
                ),
            )
            .values(review_status=ReviewStatus.pending, dismiss_reason=None)
        ),
    )
    if result.rowcount != 1:
        raise ReviewConflict("candidate is not in a dismissed state")
    session.refresh(candidate)
    session.add(
        ReviewDecision(
            candidate_id=candidate.id,
            subject_id=candidate.subject_id,
            decision=ReviewDecisionKind.reopen,
            note=note.strip(),
            score=candidate.score,
            decided_by_staff_id=actor_staff_id,
        )
    )
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="review.reopen",
        entity_type="discovery_candidate",
        entity_id=str(candidate.id),
        meta={"note": note.strip()[:200]},
    )


@dataclass
class BulkDismissResult:
    count: int
    applied: bool


def bulk_dismiss(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    reason: str,
    domain: str | None = None,
    account: str | None = None,
    dry_run: bool = True,
) -> BulkDismissResult:
    if reason == DismissReason.allowlisted:
        raise InvalidReason("'allowlisted' is system-only and can't be chosen by a reviewer")
    domain = (domain or "").strip().lower() or None
    account = (account or "").strip().lstrip("@").lower() or None
    if not (domain or account):
        raise InvalidReason("a domain or account is required")

    pending = list(
        session.scalars(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.review_status == ReviewStatus.pending
            )
        ).all()
    )
    matches = [c for c in pending if _bulk_matches(c, domain, account)]
    if dry_run:
        return BulkDismissResult(count=len(matches), applied=False)

    cap = get_settings().review_bulk_dismiss_max
    if len(matches) > cap:
        raise InvalidReason(
            f"{len(matches)} matches exceed the per-call cap of {cap}; narrow the target"
        )
    applied = 0
    for candidate in matches:
        if not _claim_pending(session, candidate.id, ReviewStatus.dismissed):
            continue  # someone else took it between the scan and now
        candidate.dismiss_reason = reason
        session.add(
            ReviewDecision(
                candidate_id=candidate.id,
                subject_id=candidate.subject_id,
                decision=ReviewDecisionKind.dismiss,
                reason=reason,
                score=candidate.score,
                decided_by_staff_id=actor_staff_id,
            )
        )
        applied += 1
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="review.bulk_dismiss",
        entity_type="discovery_candidate",
        entity_id="*",
        meta={"reason": reason, "domain": domain, "account": account, "count": applied},
    )
    return BulkDismissResult(count=applied, applied=True)


def _bulk_matches(
    candidate: DiscoveryCandidate, domain: str | None, account: str | None
) -> bool:
    if domain is not None:
        host = _host(candidate.source_url)
        if host == domain or host.endswith(f".{domain}") or _host(candidate.page_url) == domain:
            return True
    if account is not None:
        urls = " ".join(u.lower() for u in (candidate.source_url, candidate.page_url) if u)
        if account in urls:
            return True
    return False


# ── Guard helpers (used by asset delete + thumbnail cleanup) ──────────────────


def candidate_referenced_by_confirmed_case(session: Session, candidate_id: int) -> bool:
    return (
        session.scalar(
            select(Case.id)
            .where(Case.candidate_id == candidate_id, Case.status == CaseStatus.confirmed)
            .limit(1)
        )
        is not None
    )


def asset_referenced_by_confirmed_case(session: Session, asset_id: int) -> bool:
    return (
        session.scalar(
            select(Case.id)
            .where(Case.matched_asset_id == asset_id, Case.status == CaseStatus.confirmed)
            .limit(1)
        )
        is not None
    )
