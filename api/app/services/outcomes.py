"""Outcomes service (Slice 9): the only mutator of ``notice_outcomes``.

Records the platform's response to a filed notice. Only ``removed``/``countered`` move the case
(via the case service); ``rejected``/``no_response`` are pure records that keep the case Filed and
reset the follow-up timer. Outcomes are append-only — a mistake is corrected by appending a
superseding row, never by editing. See docs/specs/outcomes.md."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.models.cases import Case, CaseStatus
from api.app.models.notices import Notice
from api.app.models.outcomes import (
    NoticeOutcome,
    OutcomeKind,
    OutcomeSource,
    RecheckResult,
    UrlRecheck,
)
from api.app.services import cases as cases_svc
from api.app.services.channels import get_channel


class OutcomeStateError(Exception):
    """An outcome was recorded on a case that is not Filed → 409."""


# Outcomes that drive a case transition; the rest keep the case Filed.
_TRANSITION_FOR = {
    OutcomeKind.removed: CaseStatus.removed,
    OutcomeKind.countered: CaseStatus.countered,
}


def _today() -> date:
    return datetime.now(UTC).date()


def _default_effective_at(session: Session, case_id: int) -> date:
    """The date the platform likely acted: the start of the current consecutive ``gone`` recheck
    streak, else today. Time-to-removal uses this, not the confirmation time."""
    rows = list(
        session.scalars(
            select(UrlRecheck)
            .where(UrlRecheck.case_id == case_id)
            .order_by(UrlRecheck.id.desc())
        ).all()
    )
    streak_start: date | None = None
    for row in rows:  # newest → oldest
        if row.result != RecheckResult.gone:
            break
        streak_start = row.created_at.date()
    return streak_start or _today()


def _follow_up_due(session: Session, notice: Notice) -> datetime:
    """Next follow-up nudge = now + the platform's response window (channel), else the filed
    fallback from case_due_days."""
    settings = get_settings()
    days = settings.case_due_days_map.get("filed", 3)
    channel = get_channel(session, notice.channel_id)
    if channel is not None and channel.response_window_days:
        days = channel.response_window_days
    return datetime.now(UTC) + timedelta(days=days)


def record_outcome(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    notice: Notice,
    outcome: OutcomeKind,
    effective_at: date | None = None,
    note: str | None = None,
    source: OutcomeSource = OutcomeSource.manual,
    supersedes_id: int | None = None,
) -> NoticeOutcome:
    if CaseStatus(case.status) != CaseStatus.filed:
        raise OutcomeStateError("outcomes are recorded on a Filed case")

    row = NoticeOutcome(
        case_id=case.id, notice_id=notice.id, outcome=outcome, source=source,
        effective_at=effective_at or _default_effective_at(session, case.id),
        note=note, supersedes_id=supersedes_id, recorded_by_staff_id=actor_staff_id,
    )
    session.add(row)
    # Recording any outcome resolves a pending removal proposal (a human has acted).
    case.removal_proposed_at = None
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="case.outcome_recorded", entity_type="case", entity_id=str(case.id),
        meta={"outcome": str(outcome), "notice_id": notice.id,
              "effective_at": row.effective_at.isoformat(), "source": str(source)},
    )

    to_status = _TRANSITION_FOR.get(outcome)
    if to_status is not None:
        # `removed` COMMITS inside the transition (it enqueues the proof-of-removal capture), so
        # this is the last mutation to the case here — the outcome row + audit are already flushed.
        cases_svc.transition(
            session, workspace_id=workspace_id, actor_staff_id=actor_staff_id, case=case,
            to_status=to_status, reason=f"outcome_{outcome}",
        )
    else:
        # rejected / no_response: stays Filed; resurface on the follow-up list after the window.
        case.due_at = _follow_up_due(session, notice)
        session.flush()
    return row


def dismiss_removal_proposal(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    note: str,
) -> Case:
    """Reject an auto-proposed removal (a false positive — the content is still up). Clears the
    flag; the case stays Filed. A note is required."""
    if not note.strip():
        raise OutcomeStateError("a note is required to dismiss a removal proposal")
    case.removal_proposed_at = None
    # Remember the dismissal so the next beat doesn't immediately re-raise the same proposal from
    # the (immutable) gone rechecks that triggered it — a fresh gone streak is required.
    case.removal_dismissed_at = datetime.now(UTC)
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="case.removal_proposal_dismissed", entity_type="case", entity_id=str(case.id),
        meta={"note": note.strip()[:200]},
    )
    return case


# ── Reads ─────────────────────────────────────────────────────────────────────


def list_outcomes(session: Session, case_id: int) -> list[NoticeOutcome]:
    return list(
        session.scalars(
            select(NoticeOutcome)
            .where(NoticeOutcome.case_id == case_id)
            .order_by(NoticeOutcome.id)
        ).all()
    )


def effective_outcome(session: Session, notice_id: int) -> NoticeOutcome | None:
    """The final recorded outcome for a notice (the latest row — each correction supersedes the
    prior one, so latest-by-id is the effective state)."""
    return session.scalar(
        select(NoticeOutcome)
        .where(NoticeOutcome.notice_id == notice_id)
        .order_by(NoticeOutcome.id.desc())
        .limit(1)
    )
