"""Case lifecycle service — the ONLY code that changes ``Case.status``.

Every transition is validated against ``TRANSITIONS``, applied with a conditional
``UPDATE ... WHERE status=<from>`` (so concurrent transitions can't both win — the loser gets
a 409), and recorded as a ``CaseEvent`` (the timeline) plus an audit entry. See
docs/specs/cases.md and docs/adr/0008-case-lifecycle.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.db.session import public_session
from api.app.models.cases import (
    TERMINAL_STATES,
    Case,
    CaseEvent,
    CaseEventKind,
    CaseNote,
    CaseStatus,
)
from api.app.models.discovery import DiscoveryCandidate
from api.app.models.public import Staff, StaffWorkspaceAccess
from api.app.models.subjects import Subject
from api.app.services.claim_support import claim_support, subject_enforcement
from api.app.services.offender import offender_key

# The state machine, verbatim from CLAUDE.md (amended: +withdrawn, countered non-terminal).
TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.discovered: frozenset({CaseStatus.confirmed, CaseStatus.dismissed}),
    CaseStatus.confirmed: frozenset({CaseStatus.filed}),
    CaseStatus.filed: frozenset(
        {CaseStatus.removed, CaseStatus.countered, CaseStatus.escalated, CaseStatus.withdrawn}
    ),
    CaseStatus.countered: frozenset({CaseStatus.escalated, CaseStatus.closed}),
    CaseStatus.removed: frozenset({CaseStatus.monitoring}),
    CaseStatus.monitoring: frozenset({CaseStatus.discovered, CaseStatus.closed}),
    CaseStatus.escalated: frozenset({CaseStatus.recovered, CaseStatus.closed}),
    CaseStatus.withdrawn: frozenset(),
    CaseStatus.dismissed: frozenset(),
    CaseStatus.recovered: frozenset(),
    CaseStatus.closed: frozenset(),
}


class IllegalTransition(Exception):
    """Requested transition isn't allowed from the current state → 422."""


class CaseConflict(Exception):
    """The case changed under us (lost the conditional-update race) → 409."""


class CasePreconditionFailed(Exception):
    """A transition precondition failed (e.g. filing without a supported claim) → 422."""


class ClaimLocked(Exception):
    """claim_type can't be changed in the current state → 422."""


class DuplicateOpenCase(Exception):
    """An open case already exists for this subject + canonical URL → 409."""


def allowed_transitions(status: CaseStatus) -> list[CaseStatus]:
    return sorted(TRANSITIONS.get(status, frozenset()), key=lambda s: s.value)


def requires_evidence_pack(session: Session, case: Case) -> bool:
    """Evidence gate for ``→ filed`` (CLAUDE.md #6): the case must have at least one sealed
    capture newer than EVIDENCE_FRESHNESS_DAYS. This is the single choke point for that rule."""
    from api.app.services.evidence import has_fresh_sealed_capture

    return has_fresh_sealed_capture(session, case.id)


def _due_at_for(status: CaseStatus) -> datetime | None:
    if status in TERMINAL_STATES:
        return None
    days = get_settings().case_due_days_map.get(status.value)
    return datetime.now(UTC) + timedelta(days=days) if days is not None else None


def _supported_claims(session: Session, subject: Subject) -> set[str]:
    return {c.claim_type for c in claim_support(session, subject) if c.supported}


def _record_event(
    session: Session,
    *,
    case_id: int,
    kind: CaseEventKind,
    from_status: CaseStatus | None = None,
    to_status: CaseStatus | None = None,
    related_case_id: int | None = None,
    actor_staff_id: int | None = None,
    reason: str | None = None,
    note: str | None = None,
) -> None:
    session.add(
        CaseEvent(
            case_id=case_id,
            kind=kind,
            from_status=from_status.value if from_status else None,
            to_status=to_status.value if to_status else None,
            related_case_id=related_case_id,
            actor_staff_id=actor_staff_id,
            reason=reason,
            note=note,
        )
    )
    session.flush()


def open_case_exists(session: Session, subject_id: int, source_key: str | None) -> bool:
    """True if a non-terminal case already exists for this subject + canonical URL."""
    if source_key is None:
        return False
    return (
        session.scalar(
            select(Case.id)
            .where(
                Case.subject_id == subject_id,
                Case.source_key == source_key,
                Case.status.notin_([s.value for s in TERMINAL_STATES]),
            )
            .limit(1)
        )
        is not None
    )


def open_case_from_candidate(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    subject: Subject,
    candidate: DiscoveryCandidate,
    claim_type: str,
    related_case_id: int | None = None,
    link_note: str | None = None,
) -> Case:
    """Create a case at ``confirmed`` from a confirmed candidate. Centralizes dedupe, offender
    key, follow-up timer, the initial event, and the audit entry."""
    if open_case_exists(session, subject.id, candidate.source_key):
        raise DuplicateOpenCase("an open case already exists for this subject and URL")

    case = Case(
        subject_id=subject.id,
        candidate_id=candidate.id,
        matched_asset_id=candidate.best_match_asset_id,
        claim_type=claim_type,
        status=CaseStatus.confirmed,
        source_url=candidate.source_url,
        source_key=candidate.source_key,
        page_url=candidate.page_url,
        offender_key=offender_key(candidate.page_url or candidate.source_url),
        opened_by_staff_id=actor_staff_id,
        due_at=_due_at_for(CaseStatus.confirmed),
        # Default-deny for report imagery: every new case starts sensitive (CLAUDE.md #7).
        sensitive=True,
    )
    session.add(case)
    # The partial unique index is the real backstop against a race between the check above and
    # this insert; translate its violation into DuplicateOpenCase (409), not a raw 500. The
    # savepoint keeps the outer transaction usable after the rollback.
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise DuplicateOpenCase(
            "an open case already exists for this subject and URL"
        ) from exc
    _record_event(
        session,
        case_id=case.id,
        kind=CaseEventKind.created,
        to_status=CaseStatus.confirmed,
        actor_staff_id=actor_staff_id,
        reason="confirmed_from_review",
    )
    if related_case_id is not None:
        _record_event(
            session,
            case_id=case.id,
            kind=CaseEventKind.link,
            related_case_id=related_case_id,
            actor_staff_id=actor_staff_id,
            note=link_note,
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


def _claim_status_conditionally(session: Session, case_id: int, from_status: CaseStatus,
                                to_status: CaseStatus, due_at: datetime | None) -> bool:
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(Case)
            .where(Case.id == case_id, Case.status == from_status.value)
            # Core UPDATE doesn't fire the ORM onupdate, so bump updated_at explicitly.
            .values(status=to_status.value, due_at=due_at, updated_at=func.now())
        ),
    )
    return result.rowcount == 1


def transition(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    to_status: CaseStatus,
    reason: str | None = None,
    note: str | None = None,
) -> Case:
    from_status = CaseStatus(case.status)
    if to_status not in TRANSITIONS.get(from_status, frozenset()):
        raise IllegalTransition(f"cannot move a case from {from_status.value} to {to_status.value}")

    if to_status == CaseStatus.withdrawn and not (note and note.strip()):
        raise CasePreconditionFailed("withdrawing a filed notice requires a note")

    if to_status == CaseStatus.filed:
        _check_filing_preconditions(session, case)

    due_at = _due_at_for(to_status)
    if not _claim_status_conditionally(session, case.id, from_status, to_status, due_at):
        raise CaseConflict("case is no longer in the expected state")
    session.refresh(case)

    _record_event(
        session,
        case_id=case.id,
        kind=CaseEventKind.transition,
        from_status=from_status,
        to_status=to_status,
        actor_staff_id=actor_staff_id,
        reason=reason,
        note=note,
    )
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="case.transition",
        entity_type="case",
        entity_id=str(case.id),
        meta={"from": from_status.value, "to": to_status.value, "reason": reason},
    )
    # Proof-of-removal capture on Removed. trigger_capture COMMITS + enqueues, so it must be the
    # last thing we do to the case here (mirrors the enqueue-after-commit pattern).
    if to_status == CaseStatus.removed:
        from api.app.models.evidence import CaptureKind
        from api.app.services import evidence as evidence_svc

        evidence_svc.trigger_capture(
            session, workspace_id=workspace_id, case=case,
            kind=CaptureKind.proof_of_removal, actor_staff_id=actor_staff_id,
        )
    return case


def _check_filing_preconditions(session: Session, case: Case) -> None:
    subject = session.get(Subject, case.subject_id)
    if subject is None or not subject_enforcement(session, subject)["enforceable"]:
        raise CasePreconditionFailed("subject has no active agent authorization")
    if case.claim_type not in _supported_claims(session, subject):
        raise CasePreconditionFailed(
            f"claim '{case.claim_type}' is no longer supported for this subject"
        )
    if not requires_evidence_pack(session, case):
        raise CasePreconditionFailed(
            "a sealed evidence capture (within the freshness window) is required before filing"
        )


def change_claim(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    new_claim_type: str,
    note: str,
) -> Case:
    if CaseStatus(case.status) not in (CaseStatus.discovered, CaseStatus.confirmed):
        raise ClaimLocked(
            "claim_type is locked once filed; withdraw and re-file to change it after filing"
        )
    subject = session.get(Subject, case.subject_id)
    if subject is None or new_claim_type not in _supported_claims(session, subject):
        raise CasePreconditionFailed(f"claim '{new_claim_type}' is not supported for this subject")
    old_claim = case.claim_type
    case.claim_type = new_claim_type
    # Re-assert the invariant: ncii is ALWAYS sensitive. Reclassifying a (possibly cleared) case
    # to ncii must re-hide its imagery — otherwise change_claim is a second door around the
    # clear_sensitive guard (CLAUDE.md #7).
    if new_claim_type == "ncii":
        case.sensitive = True
    session.flush()
    _record_event(
        session,
        case_id=case.id,
        kind=CaseEventKind.claim_change,
        actor_staff_id=actor_staff_id,
        reason=f"{old_claim}->{new_claim_type}",
        note=note,
    )
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="case.claim_changed",
        entity_type="case",
        entity_id=str(case.id),
        meta={"from": old_claim, "to": new_claim_type},
    )
    return case


def refile(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    new_claim_type: str,
    note: str,
) -> Case:
    """Open a NEW case from the same candidate under a corrected claim, linked to this
    withdrawn one in both timelines. (You withdraw a wrong-claim filing, then re-file.)"""
    if CaseStatus(case.status) != CaseStatus.withdrawn:
        raise CasePreconditionFailed("only a withdrawn case can be re-filed")
    if case.candidate_id is None:
        raise CasePreconditionFailed("this case has no candidate to re-file from")
    candidate = session.get(DiscoveryCandidate, case.candidate_id)
    if candidate is None:
        raise CasePreconditionFailed("the candidate for this case no longer exists")
    subject = session.get(Subject, case.subject_id)
    if subject is None or not subject_enforcement(session, subject)["enforceable"]:
        raise CasePreconditionFailed("subject has no active agent authorization")
    if new_claim_type not in _supported_claims(session, subject):
        raise CasePreconditionFailed(f"claim '{new_claim_type}' is not supported for this subject")

    new_case = open_case_from_candidate(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        subject=subject,
        candidate=candidate,
        claim_type=new_claim_type,
        related_case_id=case.id,
        link_note=f"re-filed from withdrawn case #{case.id}: {note}",
    )
    # Reciprocal link on the withdrawn case's timeline.
    _record_event(
        session,
        case_id=case.id,
        kind=CaseEventKind.link,
        related_case_id=new_case.id,
        actor_staff_id=actor_staff_id,
        note=f"superseded by case #{new_case.id}: {note}",
    )
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="case.refiled",
        entity_type="case",
        entity_id=str(new_case.id),
        meta={"from_case": case.id, "claim_type": new_claim_type},
    )
    return new_case


def _host(url: str | None) -> str:
    from urllib.parse import urlsplit

    if not url:
        return ""
    return (urlsplit(url).hostname or "").lower()


def _is_platform_key(key: str | None) -> bool:
    """A platform/marketplace offender key (instagram:@x, etsy:shop, …) vs a bare ``domain:host``.
    Platform detection lives in services/offender.py (the same platform set as the channel
    registry); a ``domain:`` prefix means a non-platform host."""
    if not key:
        return False
    return not key.startswith("domain:")


def find_monitoring_case(
    session: Session, *, subject_id: int, candidate: DiscoveryCandidate
) -> Case | None:
    """A monitoring case for this subject that the candidate is a reappearance of (Slice 9).

    Matches by: (1) same URL (``source_key``); (2) same platform account (``offender_key``, when
    it is account-scoped); or (3) same host + same matched asset, **only for non-platform hosts**.
    Domain-alone never merges on a platform host — two different posts on instagram.com/x.com for
    the same subject are distinct offences."""
    cand_key = offender_key(candidate.page_url or candidate.source_url)
    cand_host = _host(candidate.page_url or candidate.source_url)
    cand_asset = candidate.best_match_asset_id
    monitoring = session.scalars(
        select(Case)
        .where(Case.subject_id == subject_id, Case.status == CaseStatus.monitoring)
        .order_by(Case.id.desc())
    ).all()
    for case in monitoring:
        if candidate.source_key and case.source_key == candidate.source_key:
            return case  # (1) same URL
        if _is_platform_key(cand_key) and case.offender_key == cand_key:
            return case  # (2) same platform account
        if (
            not _is_platform_key(cand_key)  # (3) host + asset, non-platform hosts only
            and cand_host
            and cand_asset is not None
            and _host(case.page_url or case.source_url) == cand_host
            and case.matched_asset_id == cand_asset
        ):
            return case
    return None


def reopen_case(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    subject: Subject,
    candidate: DiscoveryCandidate,
    case: Case,
) -> Case:
    """Reopen a monitoring case for a reappearance instead of opening a duplicate. Re-checks the
    confirm guards (consent/authorization, claim support, allowlist — a bypass is a bug), moves
    ``monitoring → discovered → confirmed`` keeping the full timeline, points the case at the new
    candidate, and triggers a fresh evidence capture. A reopened case starts a NEW filing cycle:
    the prior notice's approval is never reused (see services/notices.create_draft)."""
    if CaseStatus(case.status) != CaseStatus.monitoring:
        raise CasePreconditionFailed("only a monitoring case can be reopened")
    if subject is None or not subject_enforcement(session, subject)["enforceable"]:
        raise CasePreconditionFailed("subject has no active agent authorization")
    if case.claim_type not in _supported_claims(session, subject):
        raise CasePreconditionFailed(
            f"claim '{case.claim_type}' is no longer supported for this subject"
        )
    from api.app.services.scoring import urls_allowlisted

    if urls_allowlisted(session, candidate.source_url, candidate.page_url):
        raise CasePreconditionFailed(
            "target is on the workspace allowlist; remove it before reopening"
        )

    transition(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id, case=case,
        to_status=CaseStatus.discovered, reason="reappearance",
    )
    transition(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id, case=case,
        to_status=CaseStatus.confirmed, reason="reopened",
    )
    # Point the case at the reappearance (a same-URL reopen reuses the existing candidate).
    case.candidate_id = candidate.id
    if candidate.best_match_asset_id is not None:
        case.matched_asset_id = candidate.best_match_asset_id
    case.source_url = candidate.source_url
    case.source_key = candidate.source_key
    case.page_url = candidate.page_url
    case.offender_key = offender_key(candidate.page_url or candidate.source_url)
    case.reappearance_proposed_at = None
    case.removal_unverified_at = None
    session.flush()
    _record_event(
        session, case_id=case.id, kind=CaseEventKind.link,
        actor_staff_id=actor_staff_id,
        note=f"reopened from monitoring on candidate #{candidate.id}",
    )
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="case.reopened", entity_type="case", entity_id=str(case.id),
        meta={"candidate_id": candidate.id, "subject_id": subject.id},
    )
    # Fresh capture, like a first confirm. trigger_capture COMMITS + enqueues, so it is the last
    # action here (callers must not mutate the case afterwards).
    from api.app.models.evidence import CaptureKind
    from api.app.services import evidence as evidence_svc

    evidence_svc.trigger_capture(
        session, workspace_id=workspace_id, case=case,
        kind=CaptureKind.auto, actor_staff_id=actor_staff_id,
    )
    return case


def add_note(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    body: str,
) -> CaseNote:
    if not body.strip():
        raise CasePreconditionFailed("a note body is required")
    note = CaseNote(case_id=case.id, author_staff_id=actor_staff_id, body=body.strip())
    session.add(note)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="case.note_added",
        entity_type="case",
        entity_id=str(case.id),
    )
    return note


def assign(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    staff_id: int | None,
) -> Case:
    if staff_id is not None and not _staff_has_access(staff_id, workspace_id):
        raise CasePreconditionFailed("assignee has no access to this workspace")
    case.assigned_staff_id = staff_id
    session.flush()
    _record_event(
        session,
        case_id=case.id,
        kind=CaseEventKind.assignment,
        actor_staff_id=actor_staff_id,
        reason=str(staff_id) if staff_id is not None else "unassigned",
    )
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="case.assigned",
        entity_type="case",
        entity_id=str(case.id),
        meta={"assigned_staff_id": staff_id},
    )
    return case


def _staff_has_access(staff_id: int, workspace_id: int) -> bool:
    with public_session() as session:
        staff = session.get(Staff, staff_id)
        if staff is None:
            return False
        if staff.all_workspaces:
            return True
        return (
            session.scalar(
                select(StaffWorkspaceAccess.id).where(
                    StaffWorkspaceAccess.staff_id == staff_id,
                    StaffWorkspaceAccess.workspace_id == workspace_id,
                )
            )
            is not None
        )


def clear_sensitive(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
) -> Case:
    """A reviewer's explicit, audited action to mark a case NOT sensitive (so report thumbnails
    may render for it). Refused for ncii — those cases are always sensitive (CLAUDE.md #7).
    Idempotent: clearing an already-cleared case is a no-op but still audited."""
    if case.claim_type == "ncii":
        raise CasePreconditionFailed("ncii cases are always sensitive and can't be cleared")
    was_sensitive = case.sensitive
    case.sensitive = False
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="case.sensitive_cleared",
        entity_type="case",
        entity_id=str(case.id),
        meta={"claim_type": case.claim_type, "was_sensitive": was_sensitive},
    )
    return case


# ── Reads ──────────────────────────────────────────────────────────────────────


def get_case(session: Session, case_id: int) -> Case | None:
    return session.get(Case, case_id)


def timeline(session: Session, case_id: int) -> list[CaseEvent]:
    return list(
        session.scalars(
            select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)
        ).all()
    )


def list_notes(session: Session, case_id: int) -> list[CaseNote]:
    return list(
        session.scalars(
            select(CaseNote).where(CaseNote.case_id == case_id).order_by(CaseNote.id)
        ).all()
    )


def is_overdue(case: Case) -> bool:
    return (
        CaseStatus(case.status) not in TERMINAL_STATES
        and case.due_at is not None
        and case.due_at < datetime.now(UTC)
    )


@dataclass
class CaseFilters:
    subject_id: int | None = None
    status: str | None = None
    claim_type: str | None = None
    offender_key: str | None = None
    assigned_staff_id: int | None = None
    overdue: bool | None = None
    min_age_days: int | None = None


def list_cases(session: Session, filters: CaseFilters) -> list[Case]:
    stmt = select(Case)
    if filters.subject_id is not None:
        stmt = stmt.where(Case.subject_id == filters.subject_id)
    if filters.status is not None:
        stmt = stmt.where(Case.status == filters.status)
    if filters.claim_type is not None:
        stmt = stmt.where(Case.claim_type == filters.claim_type)
    if filters.offender_key is not None:
        stmt = stmt.where(Case.offender_key == filters.offender_key)
    if filters.assigned_staff_id is not None:
        stmt = stmt.where(Case.assigned_staff_id == filters.assigned_staff_id)
    if filters.min_age_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=filters.min_age_days)
        stmt = stmt.where(Case.created_at < cutoff)
    if filters.overdue:
        stmt = stmt.where(
            Case.due_at.is_not(None),
            Case.due_at < datetime.now(UTC),
            Case.status.notin_([s.value for s in TERMINAL_STATES]),
        )
    stmt = stmt.order_by(Case.due_at.asc().nullslast(), Case.id.desc())
    return list(session.scalars(stmt).all())


@dataclass
class OffenderGroup:
    offender_key: str
    total: int
    open: int


def offender_summary(session: Session) -> list[OffenderGroup]:
    open_case = Case.status.notin_([s.value for s in TERMINAL_STATES])
    rows = session.execute(
        select(
            Case.offender_key,
            func.count().label("total"),
            func.count().filter(open_case).label("open_count"),
        )
        .where(Case.offender_key.is_not(None))
        .group_by(Case.offender_key)
        .order_by(func.count().filter(open_case).desc(), func.count().desc())
    ).all()
    # The WHERE filters out NULL offender keys, but that's opaque to the type checker.
    return [
        OffenderGroup(offender_key=str(r[0]), total=int(r[1]), open=int(r[2])) for r in rows
    ]
