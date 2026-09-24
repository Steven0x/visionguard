"""Rights, consent, agent-authorization and claim-support routes."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.app.auth.deps import (
    get_tenant_session,
    require_role,
    require_workspace_access,
)
from api.app.config import get_settings
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.models.rights import (
    AgentAuthorization,
    ConsentRecord,
    ConsentType,
    RightsRecord,
    RightsType,
)
from api.app.services import authorizations as auth_service
from api.app.services import claim_support as claim_service
from api.app.services import consent as consent_service
from api.app.services import rights as rights_service
from api.app.services import subjects as subj_service
from api.app.services.consent import BiometricConsentBlocked
from api.app.services.documents import signed_download_url
from api.app.uploads import (
    UnsupportedFileType,
    UploadTooLarge,
    read_capped_upload,
    require_document_type,
    sanitize_filename,
)

router = APIRouter(prefix="/workspaces", tags=["records"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)
_ADMIN = require_role(StaffRole.admin)


# ── Schemas ───────────────────────────────────────────────────────────────────


class RightsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    type: RightsType
    grants_enforcement_right: bool
    file_name: str
    content_type: str
    rights_date: date | None
    expires_on: date | None
    coverage: str | None
    notes: str | None
    status: str
    created_at: datetime


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    type: ConsentType
    file_name: str
    content_type: str
    signer_name: str
    signed_date: date
    status: str
    created_at: datetime


class AuthorizationOut(BaseModel):
    id: int
    subject_id: int | None
    file_name: str | None
    signer_name: str
    authorized_date: date
    status: str
    notes: str | None
    has_file: bool
    created_at: datetime

    @classmethod
    def of(cls, a: AgentAuthorization) -> AuthorizationOut:
        return cls(
            id=a.id,
            subject_id=a.subject_id,
            file_name=a.file_name,
            signer_name=a.signer_name,
            authorized_date=a.authorized_date,
            status=a.status,
            notes=a.notes,
            has_file=a.file_key is not None,
            created_at=a.created_at,
        )


class ClaimSupportOut(BaseModel):
    claim_type: str
    supported: bool
    missing: list[str]


class ClaimSupportResponse(BaseModel):
    matrix_status: str
    claims: list[ClaimSupportOut]
    enforcement: dict
    biometrics: dict


class DownloadResponse(BaseModel):
    url: str
    expires_in: int


class RevokeIn(BaseModel):
    reason: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _read_document(file: UploadFile) -> tuple[bytes, str, str]:
    try:
        data = await read_capped_upload(file, get_settings().storage_max_upload_bytes)
        content_type = require_document_type(data)
    except (UploadTooLarge, UnsupportedFileType) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return data, content_type, sanitize_filename(file.filename)


def _require_subject(session: Session, subject_id: int) -> None:
    if subj_service.get_subject(session, subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")


def _download(url: str) -> DownloadResponse:
    return DownloadResponse(url=url, expires_in=get_settings().storage_signed_url_ttl_seconds)


# ── Rights ────────────────────────────────────────────────────────────────────


@router.get("/{workspace_id}/subjects/{subject_id}/rights", response_model=list[RightsOut])
def list_rights(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[RightsRecord]:
    _require_subject(session, subject_id)
    return rights_service.list_rights(session, subject_id)


@router.post(
    "/{workspace_id}/subjects/{subject_id}/rights",
    response_model=RightsOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_rights(
    subject_id: int,
    type: RightsType = Form(...),
    grants_enforcement_right: bool = Form(False),
    rights_date: date | None = Form(None),
    expires_on: date | None = Form(None),
    coverage: str | None = Form(None),
    notes: str | None = Form(None),
    file: UploadFile = File(...),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> RightsRecord:
    _require_subject(session, subject_id)
    data, content_type, file_name = await _read_document(file)
    return rights_service.create_rights_record(
        session,
        workspace_id=workspace.id,
        schema=workspace.schema_name,
        actor_staff_id=staff.id,
        subject_id=subject_id,
        type=type,
        grants_enforcement_right=grants_enforcement_right,
        data=data,
        content_type=content_type,
        file_name=file_name,
        rights_date=rights_date,
        expires_on=expires_on,
        coverage=coverage,
        notes=notes,
    )


@router.get(
    "/{workspace_id}/subjects/{subject_id}/rights/{rights_id}/file",
    response_model=DownloadResponse,
)
def download_rights(
    subject_id: int,
    rights_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    record = rights_service.get_rights(session, rights_id)
    if record is None or record.subject_id != subject_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return _download(
        rights_service.rights_download_url(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, record=record
        )
    )


@router.post(
    "/{workspace_id}/subjects/{subject_id}/rights/{rights_id}/revoke",
    response_model=RightsOut,
)
def revoke_rights(
    subject_id: int,
    rights_id: int,
    payload: RevokeIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> RightsRecord:
    record = rights_service.get_rights(session, rights_id)
    if record is None or record.subject_id != subject_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return rights_service.revoke_rights(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        record=record,
        reason=payload.reason,
    )


# ── Consent ───────────────────────────────────────────────────────────────────


@router.get("/{workspace_id}/subjects/{subject_id}/consent", response_model=list[ConsentOut])
def list_consent(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[ConsentRecord]:
    _require_subject(session, subject_id)
    return consent_service.list_consent(session, subject_id)


@router.post(
    "/{workspace_id}/subjects/{subject_id}/consent",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_consent(
    subject_id: int,
    type: ConsentType = Form(...),
    signer_name: str = Form(...),
    signed_date: date = Form(...),
    file: UploadFile = File(...),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> ConsentRecord:
    _require_subject(session, subject_id)
    data, content_type, file_name = await _read_document(file)
    try:
        return consent_service.create_consent_record(
            session,
            workspace_id=workspace.id,
            schema=workspace.schema_name,
            actor_staff_id=staff.id,
            subject_id=subject_id,
            type=type,
            data=data,
            content_type=content_type,
            file_name=file_name,
            signer_name=signer_name,
            signed_date=signed_date,
        )
    except BiometricConsentBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get(
    "/{workspace_id}/subjects/{subject_id}/consent/{consent_id}/file",
    response_model=DownloadResponse,
)
def download_consent(
    subject_id: int,
    consent_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    record = consent_service.get_consent(session, consent_id)
    if record is None or record.subject_id != subject_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return _download(
        consent_service.consent_download_url(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, record=record
        )
    )


@router.post(
    "/{workspace_id}/subjects/{subject_id}/consent/{consent_id}/revoke",
    response_model=ConsentOut,
)
def revoke_consent(
    subject_id: int,
    consent_id: int,
    payload: RevokeIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> ConsentRecord:
    record = consent_service.get_consent(session, consent_id)
    if record is None or record.subject_id != subject_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return consent_service.revoke_consent(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        record=record,
        reason=payload.reason,
    )


# ── Agent authorizations (workspace-level + subject-level) ────────────────────


async def _optional_document(
    file: UploadFile | None,
) -> tuple[bytes | None, str | None, str | None]:
    if file is None:
        return None, None, None
    data, content_type, file_name = await _read_document(file)
    return data, content_type, file_name


@router.get("/{workspace_id}/authorizations", response_model=list[AuthorizationOut])
def list_workspace_authorizations(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[AuthorizationOut]:
    rows = auth_service.list_authorizations(session, workspace_level_only=True)
    return [AuthorizationOut.of(a) for a in rows]


@router.post(
    "/{workspace_id}/authorizations",
    response_model=AuthorizationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_authorization(
    signer_name: str = Form(...),
    authorized_date: date = Form(...),
    notes: str | None = Form(None),
    file: UploadFile | None = File(None),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> AuthorizationOut:
    data, content_type, file_name = await _optional_document(file)
    record = auth_service.create_authorization(
        session,
        workspace_id=workspace.id,
        schema=workspace.schema_name,
        actor_staff_id=staff.id,
        subject_id=None,
        signer_name=signer_name,
        authorized_date=authorized_date,
        notes=notes,
        data=data,
        content_type=content_type,
        file_name=file_name,
    )
    return AuthorizationOut.of(record)


@router.get(
    "/{workspace_id}/subjects/{subject_id}/authorizations",
    response_model=list[AuthorizationOut],
)
def list_subject_authorizations(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[AuthorizationOut]:
    _require_subject(session, subject_id)
    rows = auth_service.list_authorizations(session, subject_id=subject_id)
    return [AuthorizationOut.of(a) for a in rows]


@router.post(
    "/{workspace_id}/subjects/{subject_id}/authorizations",
    response_model=AuthorizationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_subject_authorization(
    subject_id: int,
    signer_name: str = Form(...),
    authorized_date: date = Form(...),
    notes: str | None = Form(None),
    file: UploadFile | None = File(None),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> AuthorizationOut:
    _require_subject(session, subject_id)
    data, content_type, file_name = await _optional_document(file)
    record = auth_service.create_authorization(
        session,
        workspace_id=workspace.id,
        schema=workspace.schema_name,
        actor_staff_id=staff.id,
        subject_id=subject_id,
        signer_name=signer_name,
        authorized_date=authorized_date,
        notes=notes,
        data=data,
        content_type=content_type,
        file_name=file_name,
    )
    return AuthorizationOut.of(record)


@router.post(
    "/{workspace_id}/authorizations/{authorization_id}/revoke",
    response_model=AuthorizationOut,
)
def revoke_authorization(
    authorization_id: int,
    payload: RevokeIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> AuthorizationOut:
    record = auth_service.get_authorization(session, authorization_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    revoked = auth_service.revoke_authorization(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        record=record,
        reason=payload.reason,
    )
    return AuthorizationOut.of(revoked)


@router.get(
    "/{workspace_id}/authorizations/{authorization_id}/file",
    response_model=DownloadResponse,
)
def download_authorization(
    authorization_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    record = auth_service.get_authorization(session, authorization_id)
    if record is None or record.file_key is None or record.file_name is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no document")
    return _download(
        signed_download_url(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            entity_type="agent_authorization",
            entity_id=record.id,
            file_key=record.file_key,
            file_name=record.file_name,
        )
    )


# ── Claim support ─────────────────────────────────────────────────────────────


@router.get(
    "/{workspace_id}/subjects/{subject_id}/claim-support",
    response_model=ClaimSupportResponse,
)
def get_claim_support(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> ClaimSupportResponse:
    subject = subj_service.get_subject(session, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    claims = [
        ClaimSupportOut(claim_type=c.claim_type, supported=c.supported, missing=c.missing)
        for c in claim_service.claim_support(session, subject)
    ]
    return ClaimSupportResponse(
        matrix_status=claim_service.MATRIX_STATUS,
        claims=claims,
        enforcement=claim_service.subject_enforcement(session, subject),
        biometrics=claim_service.biometric_status(session, subject),
    )
