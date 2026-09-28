"""Removal metrics (Slice 9): removal rate + median time-to-removal per platform × claim type.

Counted **per filing (notice), not per case** — a reopened-and-refiled case contributes two
filings, so re-offences and double-removals are visible. Removal rate excludes ``withdrawn``
filings from the denominator (reported separately) and reports the still-pending count so young
filings don't silently depress the rate. Time-to-removal uses the outcome's staff-entered
``effective_at`` (when content actually went down), not the confirmation timestamp. See
docs/specs/outcomes.md."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.app.models.cases import (
    TERMINAL_STATES,
    Case,
    CaseEvent,
    CaseEventKind,
    CaseStatus,
)
from api.app.models.discovery import DiscoveryCandidate, DiscoveryRun, ReviewStatus
from api.app.models.notices import Notice, NoticeStatus
from api.app.models.outcomes import OutcomeKind, RecheckResult, UrlRecheck
from api.app.models.review import DismissReason, ReviewDecision
from api.app.models.subjects import Subject
from api.app.services.claim_support import claim_support
from api.app.services.outcomes import effective_outcome

# A notice that left `draft` is a filing (sent, transport-failed-but-recorded, or later withdrawn).
_FILED_STATUSES = (NoticeStatus.sent, NoticeStatus.delivery_failed, NoticeStatus.withdrawn)


@dataclass
class PlatformClaimMetric:
    platform: str
    claim_type: str
    filed: int = 0  # all filings, incl. withdrawn
    withdrawn: int = 0
    removed: int = 0
    # Of `removed`: split by how the take-down was confirmed, so a soft-404 platform (which never
    # returns `gone`) reports honest numbers instead of implying recheck-proven removals.
    removed_verified: int = 0  # a `gone` recheck observed the content down
    removed_staff_only: int = 0  # recorded by staff, never recheck-verified
    pending: int = 0  # eligible (filed − withdrawn) not yet removed
    removal_rate: float | None = None  # removed / (filed − withdrawn); None when none eligible
    median_days_to_removal: float | None = None
    _days: list[int] = field(default_factory=list, repr=False)


def _gone_case_ids(session: Session) -> set[int]:
    """Case ids whose URL was ever observed `gone` — the recheck-verification signal."""
    return set(
        session.scalars(
            select(UrlRecheck.case_id).where(UrlRecheck.result == RecheckResult.gone).distinct()
        ).all()
    )


def removal_metrics(session: Session) -> list[PlatformClaimMetric]:
    groups: dict[tuple[str, str], PlatformClaimMetric] = {}
    gone_case_ids = _gone_case_ids(session)
    notices = session.scalars(
        select(Notice).where(Notice.status.in_(_FILED_STATUSES))
    ).all()
    for notice in notices:
        key = (notice.platform, notice.claim_type)
        metric = groups.get(key)
        if metric is None:
            metric = groups[key] = PlatformClaimMetric(
                platform=notice.platform, claim_type=notice.claim_type
            )
        metric.filed += 1
        if notice.status == NoticeStatus.withdrawn:
            metric.withdrawn += 1
            continue
        outcome = effective_outcome(session, notice.id)
        if outcome is not None and outcome.outcome == OutcomeKind.removed:
            metric.removed += 1
            if notice.case_id in gone_case_ids:
                metric.removed_verified += 1
            else:
                metric.removed_staff_only += 1
            if notice.sent_at is not None:
                # Clamp at 0: effective_at is staff-entered and should be ≥ the filing date, but a
                # mistaken earlier date must not produce a negative time-to-removal.
                metric._days.append(
                    max(0, (outcome.effective_at - notice.sent_at.date()).days)
                )

    result: list[PlatformClaimMetric] = []
    for metric in groups.values():
        eligible = metric.filed - metric.withdrawn
        metric.pending = eligible - metric.removed
        metric.removal_rate = (metric.removed / eligible) if eligible > 0 else None
        metric.median_days_to_removal = (
            float(statistics.median(metric._days)) if metric._days else None
        )
        result.append(metric)
    result.sort(key=lambda m: (m.platform, m.claim_type))
    return result


# ── Agency report aggregates (Slice 10) ──────────────────────────────────────
# Every number the agency PDF prints comes from here — the report layer does no counting. All
# funnel counts are per FILING (notice), matching removal_metrics; snapshots are as-of. See
# docs/specs/reports.md.


@dataclass
class NeedsFromYou:
    """What the agency must supply to unblock claims, derived from claim support + review
    decisions (no new counting primitive). Subject-id lists so a per-subject report shows only
    its own; sorted for a deterministic JSON snapshot."""

    missing_authorization: list[int] = field(default_factory=list)
    ownership_rights: list[int] = field(default_factory=list)  # copyright ownership / photographer
    enforcement_consent: list[int] = field(default_factory=list)  # likeness/ncii/impersonation
    licensed_use_confirmations: int = 0  # dismissed-as-licensed decisions in the period


@dataclass
class ReportMetrics:
    period_start: date
    period_end: date
    subject_id: int | None
    found: int = 0  # cases opened (confirmed) in the period
    filed: int = 0  # filings sent in the period (incl. withdrawn)
    withdrawn: int = 0
    removed: int = 0
    removed_verified: int = 0
    removed_staff_only: int = 0
    countered: int = 0
    still_pending: int = 0  # filed, no terminal outcome yet
    median_days_to_removal: float | None = None
    # Snapshot as of `as_of`: non-terminal cases grouped by status.
    open_cases_by_status: dict[str, int] = field(default_factory=dict)
    needs_from_you: NeedsFromYou = field(default_factory=NeedsFromYou)
    highlights: list[str] = field(default_factory=list)
    _days: list[int] = field(default_factory=list, repr=False)
    # Most-hit platform (for a highlight), computed alongside the funnel.
    _platform_filings: dict[str, int] = field(default_factory=dict, repr=False)
    _min_verified_days: int | None = field(default=None, repr=False)


# `claim_support().missing` reason prefixes → the report's "Needs from you" buckets.
_NEEDS_AUTH = "active agent authorization"
_NEEDS_OWNERSHIP = "ownership rights record"
_NEEDS_CONSENT = "active enforcement consent"


def _period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """`[start 00:00 UTC, end+1 00:00 UTC)` — an explicit UTC half-open interval so period
    membership never depends on the connection's TimeZone (which `func.date()` on a timestamptz
    would). Stored timestamps are UTC-aware."""
    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_next = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    return start_dt, end_next


def report_metrics(
    session: Session,
    *,
    subject_id: int | None = None,
    start: date,
    end: date,
    as_of: datetime,
) -> ReportMetrics:
    m = ReportMetrics(period_start=start, period_end=end, subject_id=subject_id)
    gone_case_ids = _gone_case_ids(session)
    start_dt, end_next = _period_bounds(start, end)

    # ── Found: cases opened (confirmed) in the period ──
    found_stmt = select(func.count()).select_from(Case).where(
        Case.created_at >= start_dt, Case.created_at < end_next
    )
    if subject_id is not None:
        found_stmt = found_stmt.where(Case.subject_id == subject_id)
    m.found = int(session.scalar(found_stmt) or 0)

    # ── Funnel over filings sent in the period ──
    notice_stmt = (
        select(Notice)
        .join(Case, Case.id == Notice.case_id)
        .where(
            Notice.status.in_(_FILED_STATUSES),
            Notice.sent_at.is_not(None),
            Notice.sent_at >= start_dt,
            Notice.sent_at < end_next,
        )
    )
    if subject_id is not None:
        notice_stmt = notice_stmt.where(Case.subject_id == subject_id)
    for notice in session.scalars(notice_stmt).all():
        m.filed += 1
        m._platform_filings[notice.platform] = m._platform_filings.get(notice.platform, 0) + 1
        if notice.status == NoticeStatus.withdrawn:
            m.withdrawn += 1
            continue
        outcome = effective_outcome(session, notice.id)
        kind = outcome.outcome if outcome is not None else None
        if kind == OutcomeKind.removed:
            m.removed += 1
            verified = notice.case_id in gone_case_ids
            if verified:
                m.removed_verified += 1
            else:
                m.removed_staff_only += 1
            if notice.sent_at is not None and outcome is not None:
                days = max(0, (outcome.effective_at - notice.sent_at.date()).days)
                m._days.append(days)
                if verified and (m._min_verified_days is None or days < m._min_verified_days):
                    m._min_verified_days = days
        elif kind == OutcomeKind.countered:
            m.countered += 1
        else:  # None / rejected / no_response — still filed
            m.still_pending += 1
    m.median_days_to_removal = (
        float(statistics.median(m._days)) if m._days else None
    )

    # ── Open cases by status (snapshot) ──
    open_stmt = (
        select(Case.status, func.count())
        .where(Case.status.notin_([s.value for s in TERMINAL_STATES]))
        .group_by(Case.status)
    )
    if subject_id is not None:
        open_stmt = open_stmt.where(Case.subject_id == subject_id)
    m.open_cases_by_status = {
        str(status): int(count) for status, count in session.execute(open_stmt).all()
    }

    m.needs_from_you = _needs_from_you(session, subject_id=subject_id, start=start, end=end)
    m.highlights = _highlights(m)
    return m


def _in_scope_subject_ids(session: Session, subject_id: int | None) -> list[int]:
    """Subjects a report's 'Needs from you' covers: the given one, or every subject with a
    non-terminal case or a pending discovery candidate."""
    if subject_id is not None:
        return [subject_id]
    with_open_case = set(
        session.scalars(
            select(Case.subject_id)
            .where(Case.status.notin_([s.value for s in TERMINAL_STATES]))
            .distinct()
        ).all()
    )
    with_pending = set(
        session.scalars(
            select(DiscoveryCandidate.subject_id)
            .where(DiscoveryCandidate.review_status == ReviewStatus.pending)
            .distinct()
        ).all()
    )
    return sorted(with_open_case | with_pending)


def _needs_from_you(
    session: Session, *, subject_id: int | None, start: date, end: date
) -> NeedsFromYou:
    needs = NeedsFromYou()
    scope_ids = _in_scope_subject_ids(session, subject_id)
    for sid in scope_ids:
        subject = session.get(Subject, sid)
        if subject is None:  # pragma: no cover - FK/scoping guarantees presence
            continue
        missing = {reason for c in claim_support(session, subject) for reason in c.missing}
        if any(r.startswith(_NEEDS_AUTH) for r in missing):
            needs.missing_authorization.append(sid)
        if any(r.startswith(_NEEDS_OWNERSHIP) for r in missing):
            needs.ownership_rights.append(sid)
        if any(r.startswith(_NEEDS_CONSENT) for r in missing):
            needs.enforcement_consent.append(sid)

    # Licensed dismissals in the period, restricted to the in-scope subjects (spec) — so a
    # subject with no open case / pending candidate doesn't inflate a whole-workspace report.
    start_dt, end_next = _period_bounds(start, end)
    licensed_stmt = select(func.count()).select_from(ReviewDecision).where(
        ReviewDecision.reason == DismissReason.licensed,
        ReviewDecision.subject_id.in_(scope_ids),
        ReviewDecision.decided_at >= start_dt,
        ReviewDecision.decided_at < end_next,
    )
    needs.licensed_use_confirmations = int(session.scalar(licensed_stmt) or 0)
    return needs


def _highlights(m: ReportMetrics) -> list[str]:
    """2–3 plain-language highlights, pure functions of the funnel numbers (no new queries)."""
    out: list[str] = []
    if m.removed:
        out.append(f"{m.removed} removed this period")
    if m._min_verified_days is not None:
        out.append(f"fastest verified removal in {m._min_verified_days}d")
    if m._platform_filings:
        platform, n = max(m._platform_filings.items(), key=lambda kv: (kv[1], kv[0]))
        out.append(f"most-hit platform: {platform} ({n} filings)")
    return out[:3]


# ── Internal metrics page (Slice 10, per workspace) ───────────────────────────


@dataclass
class ProviderCost:
    provider: str
    cost_cents: int


@dataclass
class MetricsSummary:
    removals: list[PlatformClaimMetric] = field(default_factory=list)
    review_precision: float | None = None  # (filed − withdrawn) / filed
    wrong_filing_rate: float | None = None  # withdrawn / filed
    re_upload_rate: float | None = None  # reopened / removed (from the timeline)
    review_minutes_per_case: float | None = None  # median(decided_at − shown_at)
    provider_cost: list[ProviderCost] = field(default_factory=list)
    provider_cost_total_cents: int = 0


def metrics_summary(session: Session) -> MetricsSummary:
    summary = MetricsSummary(removals=removal_metrics(session))

    # Review precision + wrong-filing rate, over all filings (per-notice, all-time).
    filed = withdrawn = 0
    for notice in session.scalars(
        select(Notice).where(Notice.status.in_(_FILED_STATUSES))
    ).all():
        filed += 1
        if notice.status == NoticeStatus.withdrawn:
            withdrawn += 1
    if filed:
        summary.wrong_filing_rate = withdrawn / filed
        summary.review_precision = (filed - withdrawn) / filed

    # Re-upload rate = reopened / removed, both counted from the case timeline (real transitions).
    reopened = int(
        session.scalar(
            select(func.count()).select_from(CaseEvent).where(
                CaseEvent.kind == CaseEventKind.transition,
                CaseEvent.to_status == CaseStatus.discovered.value,
                CaseEvent.reason == "reappearance",
            )
        )
        or 0
    )
    removed_transitions = int(
        session.scalar(
            select(func.count()).select_from(CaseEvent).where(
                CaseEvent.kind == CaseEventKind.transition,
                CaseEvent.to_status == CaseStatus.removed.value,
            )
        )
        or 0
    )
    if removed_transitions:
        summary.re_upload_rate = reopened / removed_transitions

    # Review minutes per case = median(decided_at − shown_at) over decided candidates that were
    # stamped shown. Join the decision to its candidate's shown_at.
    rows = session.execute(
        select(ReviewDecision.decided_at, DiscoveryCandidate.shown_at)
        .join(DiscoveryCandidate, DiscoveryCandidate.id == ReviewDecision.candidate_id)
        .where(DiscoveryCandidate.shown_at.is_not(None))
    ).all()
    minutes = [
        max(0.0, (decided_at - shown_at).total_seconds() / 60.0)
        for decided_at, shown_at in rows
        if decided_at is not None and shown_at is not None
    ]
    if minutes:
        summary.review_minutes_per_case = float(statistics.median(minutes))

    # Provider cost per workspace = sum(estimated_cost_cents) grouped by provider.
    cost_rows = session.execute(
        select(DiscoveryRun.provider, func.coalesce(func.sum(DiscoveryRun.estimated_cost_cents), 0))
        .where(DiscoveryRun.provider.is_not(None))
        .group_by(DiscoveryRun.provider)
        .order_by(DiscoveryRun.provider)
    ).all()
    summary.provider_cost = [
        ProviderCost(provider=str(provider), cost_cents=int(cents)) for provider, cents in cost_rows
    ]
    summary.provider_cost_total_cents = sum(pc.cost_cents for pc in summary.provider_cost)
    return summary
