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

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models.notices import Notice, NoticeStatus
from api.app.models.outcomes import OutcomeKind, RecheckResult, UrlRecheck
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


def removal_metrics(session: Session) -> list[PlatformClaimMetric]:
    groups: dict[tuple[str, str], PlatformClaimMetric] = {}
    # Case ids whose URL was ever observed `gone` — the recheck-verification signal.
    gone_case_ids = set(
        session.scalars(
            select(UrlRecheck.case_id).where(UrlRecheck.result == RecheckResult.gone).distinct()
        ).all()
    )
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
