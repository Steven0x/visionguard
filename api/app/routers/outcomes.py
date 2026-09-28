"""Outcomes & re-upload-watch routes (Slice 9): record platform responses on a filed notice,
confirm/dismiss auto-proposals, reopen a monitored case's reappearance, the follow-up list, the
recheck history, and the removal metrics."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.models.cases import Case, CaseStatus
from api.app.models.outcomes import OutcomeKind
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.models.subjects import Subject
from api.app.services import cases as cases_svc
from api.app.services import metrics as metrics_svc
from api.app.services import notices as notices_svc
from api.app.services import outcomes as svc
from api.app.services import recheck as recheck_svc
from api.app.services import review as review_svc

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["outcomes"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)


# ── Schemas ───────────────────────────────────────────────────────────────────


class OutcomeOut(BaseModel):
    id: int
    case_id: int
    notice_id: int
    outcome: str
    source: str
    effective_at: date
    note: str | None
    supersedes_id: int | None
    recorded_by_staff_id: int | None
    created_at: datetime


class OutcomesDetailOut(BaseModel):
    outcomes: list[OutcomeOut]
    effective_outcome: str | None
    removal_proposed_at: datetime | None
    reappearance_proposed_at: datetime | None
    removal_unverified_at: datetime | None


class RecordOutcomeIn(BaseModel):
    outcome: OutcomeKind
    effective_at: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    # Correct an earlier outcome on the same notice by appending a superseding row (append-only —
    # the prior row is never edited). Only valid while the case is still Filed.
    supersedes_id: int | None = None


class DismissProposalIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class RecheckOut(BaseModel):
    id: int
    case_id: int
    probed_url: str
    http_status: int | None
    result: str
    detail: str | None
    created_at: datetime


class MetricOut(BaseModel):
    platform: str
    claim_type: str
    filed: int
    withdrawn: int
    removed: int
    removed_verified: int
    removed_staff_only: int
    pending: int
    removal_rate: float | None
    median_days_to_removal: float | None


class FollowUpOut(BaseModel):
    case_id: int
    subject_id: int
    claim_type: str
    offender_key: str | None
    due_at: datetime | None
    source_url: str | None
    # "overdue" (filed, past its platform window) or "removal_unverified" (removed but the URL is
    # still serving — a human must confirm-close or reopen).
    reason: str


def _case_or_404(session: Session, case_id: int) -> Case:
    case = cases_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return case


def _http(code: int, exc: Exception) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


def _detail(session: Session, case: Case) -> OutcomesDetailOut:
    outcomes = svc.list_outcomes(session, case.id)
    notice = notices_svc.get_notice_for_case(session, case.id)
    eff = svc.effective_outcome(session, notice.id) if notice is not None else None
    return OutcomesDetailOut(
        outcomes=[OutcomeOut.model_validate(o, from_attributes=True) for o in outcomes],
        effective_outcome=str(eff.outcome) if eff is not None else None,
        removal_proposed_at=case.removal_proposed_at,
        reappearance_proposed_at=case.reappearance_proposed_at,
        removal_unverified_at=case.removal_unverified_at,
    )


# ── Outcomes ────────────────────────────────────────────────────────────────────


@router.get("/cases/{case_id}/outcomes", response_model=OutcomesDetailOut)
def get_outcomes(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> OutcomesDetailOut:
    case = _case_or_404(session, case_id)
    return _detail(session, case)


@router.post("/cases/{case_id}/outcomes", response_model=OutcomesDetailOut,
             status_code=status.HTTP_201_CREATED)
def record_outcome(
    case_id: int,
    payload: RecordOutcomeIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> OutcomesDetailOut:
    case = _case_or_404(session, case_id)
    notice = notices_svc.get_notice_for_case(session, case.id)
    if notice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no filed notice for this case"
        )
    try:
        svc.record_outcome(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, case=case,
            notice=notice, outcome=payload.outcome, effective_at=payload.effective_at,
            note=payload.note, supersedes_id=payload.supersedes_id,
        )
    except svc.OutcomeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    except (cases_svc.IllegalTransition, cases_svc.CasePreconditionFailed) as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    except cases_svc.CaseConflict as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    return _detail(session, _case_or_404(session, case_id))


@router.post("/cases/{case_id}/outcomes/dismiss-removal-proposal",
             response_model=OutcomesDetailOut)
def dismiss_removal_proposal(
    case_id: int,
    payload: DismissProposalIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> OutcomesDetailOut:
    case = _case_or_404(session, case_id)
    try:
        svc.dismiss_removal_proposal(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, case=case,
            note=payload.note,
        )
    except svc.OutcomeStateError as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    return _detail(session, case)


@router.post("/cases/{case_id}/reopen", response_model=OutcomesDetailOut)
def reopen_case(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> OutcomesDetailOut:
    """Confirm a same-URL reappearance proposal on a monitoring case (reuses its existing
    candidate). New-URL reappearances reopen automatically at confirm time in the review flow."""
    case = _case_or_404(session, case_id)
    if case.candidate_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="this case has no candidate to reopen from",
        )
    candidate = review_svc.get_candidate(session, case.candidate_id)
    subject = session.get(Subject, case.subject_id)
    if candidate is None or subject is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="candidate or subject missing for reopen",
        )
    try:
        cases_svc.reopen_case(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, subject=subject,
            candidate=candidate, case=case,
        )
    except cases_svc.CasePreconditionFailed as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    except (cases_svc.IllegalTransition, cases_svc.CaseConflict) as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    return _detail(session, _case_or_404(session, case_id))


@router.get("/cases/{case_id}/rechecks", response_model=list[RecheckOut])
def list_rechecks(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[RecheckOut]:
    _case_or_404(session, case_id)
    return [
        RecheckOut.model_validate(r, from_attributes=True)
        for r in recheck_svc.list_rechecks(session, case_id)
    ]


# ── Follow-ups + metrics ────────────────────────────────────────────────────────


@router.get("/follow-ups", response_model=list[FollowUpOut])
def follow_ups(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[FollowUpOut]:
    """Things needing a human: filed cases overdue on their platform window, plus removed cases
    whose take-down the rechecks couldn't verify (soft-404 — confirm-close or reopen)."""
    overdue = cases_svc.list_cases(
        session, cases_svc.CaseFilters(status=CaseStatus.filed.value, overdue=True)
    )
    unverified = cases_svc.list_cases(
        session, cases_svc.CaseFilters(status=CaseStatus.monitoring.value)
    )
    items = [
        FollowUpOut(
            case_id=c.id, subject_id=c.subject_id, claim_type=c.claim_type,
            offender_key=c.offender_key, due_at=c.due_at, source_url=c.source_url,
            reason="overdue",
        )
        for c in overdue
    ]
    items += [
        FollowUpOut(
            case_id=c.id, subject_id=c.subject_id, claim_type=c.claim_type,
            offender_key=c.offender_key, due_at=c.due_at, source_url=c.source_url,
            reason="removal_unverified",
        )
        for c in unverified
        if c.removal_unverified_at is not None
    ]
    return items


@router.get("/metrics/removals", response_model=list[MetricOut])
def removal_metrics(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[MetricOut]:
    return [
        MetricOut(
            platform=m.platform, claim_type=m.claim_type, filed=m.filed,
            withdrawn=m.withdrawn, removed=m.removed, removed_verified=m.removed_verified,
            removed_staff_only=m.removed_staff_only, pending=m.pending,
            removal_rate=m.removal_rate, median_days_to_removal=m.median_days_to_removal,
        )
        for m in metrics_svc.removal_metrics(session)
    ]
