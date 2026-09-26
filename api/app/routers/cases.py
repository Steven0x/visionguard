"""Case routes: list/grouping, detail + timeline, and the guarded state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy.orm import Session

from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.models.cases import Case, CaseStatus
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import cases as svc
from api.app.services.claim_support import ensure_known_claim

ClaimType = Annotated[str, AfterValidator(ensure_known_claim)]

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["cases"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)


# ── Schemas ───────────────────────────────────────────────────────────────────


class CaseOut(BaseModel):
    id: int
    subject_id: int
    candidate_id: int | None
    matched_asset_id: int | None
    claim_type: str
    status: CaseStatus
    source_url: str | None
    offender_key: str | None
    assigned_staff_id: int | None
    due_at: datetime | None
    overdue: bool
    created_at: datetime

    @classmethod
    def of(cls, c: Case) -> CaseOut:
        return cls(
            id=c.id,
            subject_id=c.subject_id,
            candidate_id=c.candidate_id,
            matched_asset_id=c.matched_asset_id,
            claim_type=c.claim_type,
            status=CaseStatus(c.status),
            source_url=c.source_url,
            offender_key=c.offender_key,
            assigned_staff_id=c.assigned_staff_id,
            due_at=c.due_at,
            overdue=svc.is_overdue(c),
            created_at=c.created_at,
        )


class CaseEventOut(BaseModel):
    id: int
    kind: str
    from_status: str | None
    to_status: str | None
    related_case_id: int | None
    actor_staff_id: int | None
    reason: str | None
    note: str | None
    created_at: datetime


class CaseNoteOut(BaseModel):
    id: int
    author_staff_id: int | None
    body: str
    created_at: datetime


class CaseDetailOut(BaseModel):
    case: CaseOut
    allowed_transitions: list[str]
    timeline: list[CaseEventOut]
    notes: list[CaseNoteOut]


class OffenderGroupOut(BaseModel):
    offender_key: str
    total: int
    open: int


class TransitionIn(BaseModel):
    to_status: CaseStatus
    reason: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=2000)


class ClaimIn(BaseModel):
    claim_type: ClaimType
    note: str = Field(min_length=1, max_length=2000)


class RefileIn(BaseModel):
    claim_type: ClaimType
    note: str = Field(min_length=1, max_length=2000)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class AssignIn(BaseModel):
    staff_id: int | None


def _case_or_404(session: Session, case_id: int) -> Case:
    case = svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return case


def _map_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, (svc.CaseConflict, svc.DuplicateOpenCase)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


# ── Reads ─────────────────────────────────────────────────────────────────────


@router.get("/cases", response_model=list[CaseOut])
def list_cases(
    subject_id: int | None = None,
    status_: str | None = Query(default=None, alias="status"),
    claim_type: str | None = None,
    offender_key: str | None = None,
    assigned_staff_id: int | None = None,
    overdue: bool | None = None,
    min_age_days: int | None = Query(default=None, ge=0),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[CaseOut]:
    cases = svc.list_cases(
        session,
        svc.CaseFilters(
            subject_id=subject_id,
            status=status_,
            claim_type=claim_type,
            offender_key=offender_key,
            assigned_staff_id=assigned_staff_id,
            overdue=overdue,
            min_age_days=min_age_days,
        ),
    )
    return [CaseOut.of(c) for c in cases]


@router.get("/cases/offenders", response_model=list[OffenderGroupOut])
def offenders(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[OffenderGroupOut]:
    return [
        OffenderGroupOut(offender_key=g.offender_key, total=g.total, open=g.open)
        for g in svc.offender_summary(session)
    ]


@router.get("/cases/{case_id}", response_model=CaseDetailOut)
def get_case(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaseDetailOut:
    case = _case_or_404(session, case_id)
    events = svc.timeline(session, case_id)
    notes = svc.list_notes(session, case_id)
    return CaseDetailOut(
        case=CaseOut.of(case),
        allowed_transitions=[s.value for s in svc.allowed_transitions(CaseStatus(case.status))],
        timeline=[CaseEventOut.model_validate(e, from_attributes=True) for e in events],
        notes=[CaseNoteOut.model_validate(n, from_attributes=True) for n in notes],
    )


# ── Mutations (all through the case service) ──────────────────────────────────


@router.post("/cases/{case_id}/transition", response_model=CaseOut)
def transition(
    case_id: int,
    payload: TransitionIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaseOut:
    case = _case_or_404(session, case_id)
    try:
        updated = svc.transition(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            case=case,
            to_status=payload.to_status,
            reason=payload.reason,
            note=payload.note,
        )
    except (svc.IllegalTransition, svc.CasePreconditionFailed, svc.CaseConflict) as exc:
        raise _map_errors(exc) from exc
    return CaseOut.of(updated)


@router.post("/cases/{case_id}/claim", response_model=CaseOut)
def change_claim(
    case_id: int,
    payload: ClaimIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaseOut:
    case = _case_or_404(session, case_id)
    try:
        updated = svc.change_claim(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            case=case,
            new_claim_type=payload.claim_type,
            note=payload.note,
        )
    except (svc.ClaimLocked, svc.CasePreconditionFailed) as exc:
        raise _map_errors(exc) from exc
    return CaseOut.of(updated)


@router.post("/cases/{case_id}/refile", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def refile(
    case_id: int,
    payload: RefileIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaseOut:
    case = _case_or_404(session, case_id)
    try:
        new_case = svc.refile(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            case=case,
            new_claim_type=payload.claim_type,
            note=payload.note,
        )
    except (svc.CasePreconditionFailed, svc.DuplicateOpenCase) as exc:
        raise _map_errors(exc) from exc
    return CaseOut.of(new_case)


@router.post(
    "/cases/{case_id}/notes",
    response_model=CaseNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def add_note(
    case_id: int,
    payload: NoteIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaseNoteOut:
    case = _case_or_404(session, case_id)
    note = svc.add_note(
        session, workspace_id=workspace.id, actor_staff_id=staff.id, case=case, body=payload.body
    )
    return CaseNoteOut.model_validate(note, from_attributes=True)


@router.post("/cases/{case_id}/assign", response_model=CaseOut)
def assign(
    case_id: int,
    payload: AssignIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaseOut:
    case = _case_or_404(session, case_id)
    try:
        updated = svc.assign(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            case=case,
            staff_id=payload.staff_id,
        )
    except svc.CasePreconditionFailed as exc:
        raise _map_errors(exc) from exc
    return CaseOut.of(updated)
