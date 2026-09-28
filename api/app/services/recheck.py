"""URL re-check service (Slice 9): probe an open case's URL, append the result, and *propose*
(never assert) a removal or a reappearance for a human to confirm.

Judgement calls, all in docs/specs/outcomes.md / ADR 0012:
- Probe ``page_url`` (the hosting page), not the CDN ``source_url`` — CDN links expire (false
  gone) and keep serving after removal (false live).
- ``live`` is NEVER proof (platforms soft-404 with a 200). Nothing auto-transitions on it.
- A removal is proposed only when the two most-recent checks are both ``gone`` and ≥24h apart (a
  single gone can be a geo-block / login wall / rate limit). A reappearance is proposed only on a
  ``gone → live`` transition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.models.cases import Case, CaseEvent, CaseStatus
from api.app.models.outcomes import RecheckResult, UrlRecheck
from api.app.net.fetcher import Fetcher, ProbeResult, get_fetcher
from api.app.net.ssrf import SsrfError

# HTTP statuses that mean the content is genuinely gone (not a login wall / rate limit).
_GONE_STATUSES = frozenset({404, 410, 451})


def recheck_url(case: Case) -> str | None:
    """The URL to probe: the hosting page first, the (CDN) source only as a fallback."""
    return case.page_url or case.source_url


def classify(probe: ProbeResult) -> RecheckResult:
    status = probe.http_status
    if status in _GONE_STATUSES:
        return RecheckResult.gone
    if status is not None and 200 <= status < 300:
        return RecheckResult.live
    if status is not None:
        return RecheckResult.error  # other 4xx (401/403/429) / 5xx → inconclusive
    # No HTTP status: judge by the connection outcome. A refused/failed connection is a gone
    # signal; a timeout is inconclusive.
    if not probe.reachable and (probe.error_kind or "").startswith("connect"):
        return RecheckResult.gone
    return RecheckResult.error


def record_recheck(
    session: Session,
    *,
    case_id: int,
    probed_url: str,
    result: RecheckResult,
    http_status: int | None,
    detail: str | None,
) -> UrlRecheck:
    row = UrlRecheck(
        case_id=case_id, probed_url=probed_url, result=result,
        http_status=http_status, detail=detail,
    )
    session.add(row)
    session.flush()
    return row


def _recent(session: Session, case_id: int, limit: int) -> list[UrlRecheck]:
    return list(
        session.scalars(
            select(UrlRecheck)
            .where(UrlRecheck.case_id == case_id)
            .order_by(UrlRecheck.id.desc())
            .limit(limit)
        ).all()
    )


def evaluate_filed(session: Session, *, workspace_id: int, case: Case) -> bool:
    """Propose a removal when the two most-recent checks are both ``gone`` and ≥ the configured
    gap apart. Idempotent — a standing proposal is not re-flagged. Returns True on a new proposal.
    """
    if case.removal_proposed_at is not None:
        return False
    recent = _recent(session, case.id, 2)
    if len(recent) < 2:
        return False
    newest, prior = recent[0], recent[1]
    if newest.result != RecheckResult.gone or prior.result != RecheckResult.gone:
        return False
    gap = timedelta(hours=get_settings().recheck_min_gap_hours)
    if newest.created_at - prior.created_at < gap:
        return False
    # A prior dismissal suppresses re-proposal until a fresh gone streak accrues entirely after it
    # (otherwise the immutable gone rechecks would re-trigger the same proposal every beat).
    if case.removal_dismissed_at is not None and prior.created_at <= case.removal_dismissed_at:
        return False
    case.removal_proposed_at = datetime.now(UTC)
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=None,
        action="case.removal_proposed", entity_type="case", entity_id=str(case.id),
        meta={"probed_url": newest.probed_url},
    )
    return True


def evaluate_monitoring(session: Session, *, workspace_id: int, case: Case) -> bool:
    """Propose a reappearance ONLY on a ``gone → live`` transition (a previously-down URL is
    serving again) — never on a plain standing ``live``. Returns True on a new proposal."""
    if case.reappearance_proposed_at is not None:
        return False
    recent = _recent(session, case.id, 2)
    if len(recent) < 2:
        return False
    newest, prior = recent[0], recent[1]
    if not (newest.result == RecheckResult.live and prior.result == RecheckResult.gone):
        return False
    case.reappearance_proposed_at = datetime.now(UTC)
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=None,
        action="case.reappearance_proposed", entity_type="case", entity_id=str(case.id),
        meta={"probed_url": newest.probed_url},
    )
    return True


def run_recheck(
    session: Session,
    *,
    workspace_id: int,
    case: Case,
    fetcher: Fetcher | None = None,
) -> UrlRecheck | None:
    """Probe an open filed/monitoring case's URL, append the result, and run the matching
    proposal evaluation. Never raises for network/SSRF issues — those are recorded as ``error``.
    """
    url = recheck_url(case)
    if url is None:
        return None
    fetcher = fetcher or get_fetcher()
    http_status: int | None = None
    detail: str | None = None
    try:
        probe = fetcher.probe(url)
        result = classify(probe)
        http_status = probe.http_status
        detail = probe.error_kind
    except SsrfError as exc:
        # Bad URL / blocked IP / DNS failure → inconclusive, not "gone".
        result = RecheckResult.error
        detail = f"ssrf:{exc}"[:500]
    row = record_recheck(
        session, case_id=case.id, probed_url=url, result=result,
        http_status=http_status, detail=detail,
    )
    status = CaseStatus(case.status)
    if status == CaseStatus.filed:
        evaluate_filed(session, workspace_id=workspace_id, case=case)
    elif status == CaseStatus.monitoring:
        evaluate_monitoring(session, workspace_id=workspace_id, case=case)
    return row


def _removed_at(session: Session, case_id: int) -> datetime | None:
    """When the case was last recorded as removed (the removed transition's timeline event)."""
    return session.scalar(
        select(CaseEvent.created_at)
        .where(
            CaseEvent.case_id == case_id,
            CaseEvent.to_status == CaseStatus.removed.value,
        )
        .order_by(CaseEvent.id.desc())
        .limit(1)
    )


def removal_unverified(session: Session, case: Case) -> bool:
    """True when a removed case was probed since the removal but **never observed ``gone``** — the
    URL kept serving a page (soft-404), or was only ever unreachable/blocked (login wall, rate
    limit), so the take-down was never recheck-verified. Only a ``gone`` observation verifies a
    removal, so anything else (all ``live``, all ``error``, or a mix) leaves it unverified.

    No recheck at all since the removal → not flagged (nothing contradicts a staff-confirmed
    removal); a single ``gone`` since the removal verifies it and clears the doubt.
    """
    removed_at = _removed_at(session, case.id)
    if removed_at is None:
        return False
    rows = list(
        session.scalars(
            select(UrlRecheck).where(
                UrlRecheck.case_id == case.id, UrlRecheck.created_at >= removed_at
            )
        ).all()
    )
    return bool(rows) and not any(r.result == RecheckResult.gone for r in rows)


def list_rechecks(session: Session, case_id: int) -> list[UrlRecheck]:
    return list(
        session.scalars(
            select(UrlRecheck)
            .where(UrlRecheck.case_id == case_id)
            .order_by(UrlRecheck.id.desc())
        ).all()
    )
