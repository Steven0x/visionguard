"""Subject routes: list/create/get/edit/archive and CSV import (preview + commit)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from api.app.auth.deps import (
    get_tenant_session,
    require_role,
    require_workspace_access,
)
from api.app.constants import SUBJECT_IMPORT_MAX_BYTES, US_STATES
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.models.subjects import Subject, SubjectStatus
from api.app.services import subjects as subj_service
from api.app.services.subjects import CsvFileError, CsvRowErrors

router = APIRouter(prefix="/workspaces/{workspace_id}/subjects", tags=["subjects"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)
_UPLOAD_CHUNK = 64 * 1024


async def _read_capped(file: UploadFile) -> bytes:
    """Read an upload in chunks, aborting past the byte cap so a huge body can't be
    buffered whole into memory before the size check."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK):
        total += len(chunk)
        if total > SUBJECT_IMPORT_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"file too large (limit {SUBJECT_IMPORT_MAX_BYTES} bytes)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ── Schemas ───────────────────────────────────────────────────────────────────


class SubjectIn(BaseModel):
    legal_name: str
    stage_names: list[str] = []
    handles: list[str] = []
    residence_state: str | None = None
    notes: str | None = None

    @field_validator("legal_name")
    @classmethod
    def _legal_name_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("legal_name is required")
        return v

    @field_validator("residence_state")
    @classmethod
    def _valid_state(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip().upper()
        if not s:
            return None
        if s not in US_STATES:
            raise ValueError("invalid residence_state")
        return s


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    legal_name: str
    stage_names: list[str]
    handles: list[str]
    residence_state: str | None
    biometrics_blocked: bool
    status: SubjectStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PreviewRow(BaseModel):
    row_no: int
    values: dict
    errors: list[str]


class PreviewResponse(BaseModel):
    rows: list[PreviewRow]
    has_errors: bool


class ImportResult(BaseModel):
    imported: int


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[SubjectOut])
def list_subjects(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
    status_filter: Literal["active", "archived", "all"] = Query("active", alias="status"),
) -> list[Subject]:
    return subj_service.list_subjects(session, status_filter=status_filter)


@router.post("", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(
    payload: SubjectIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Subject:
    return subj_service.create_subject(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        legal_name=payload.legal_name,
        stage_names=payload.stage_names,
        handles=payload.handles,
        residence_state=payload.residence_state,
        notes=payload.notes,
    )


# Import routes are declared before /{subject_id} so "import" isn't parsed as an id.
@router.post("/import/preview", response_model=PreviewResponse)
async def import_preview(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
    file: UploadFile = File(...),
) -> PreviewResponse:
    raw = await _read_capped(file)
    existing_active = subj_service.list_subjects(session, status_filter="active")
    try:
        rows = subj_service.parse_and_validate(raw, existing_active)
    except CsvFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return PreviewResponse(
        rows=[PreviewRow(row_no=r.row_no, values=r.values, errors=r.errors) for r in rows],
        has_errors=any(r.errors for r in rows),
    )


@router.post("/import/commit", response_model=ImportResult)
async def import_commit(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
    file: UploadFile = File(...),
) -> ImportResult:
    raw = await _read_capped(file)
    try:
        count = subj_service.import_commit(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            raw=raw,
        )
    except CsvFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except CsvRowErrors as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "csv has invalid rows; nothing was imported",
                "rows": [
                    {"row_no": r.row_no, "errors": r.errors}
                    for r in exc.rows
                    if r.errors
                ],
            },
        ) from exc
    return ImportResult(imported=count)


@router.get("/{subject_id}", response_model=SubjectOut)
def get_subject(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Subject:
    subject = subj_service.get_subject(session, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    return subject


@router.patch("/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int,
    payload: SubjectIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Subject:
    subject = subj_service.get_subject(session, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    return subj_service.update_subject(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        subject=subject,
        legal_name=payload.legal_name,
        stage_names=payload.stage_names,
        handles=payload.handles,
        residence_state=payload.residence_state,
        notes=payload.notes,
    )


@router.post("/{subject_id}/archive", response_model=SubjectOut)
def archive_subject(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Subject:
    subject = subj_service.get_subject(session, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    return subj_service.archive_subject(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        subject=subject,
    )
