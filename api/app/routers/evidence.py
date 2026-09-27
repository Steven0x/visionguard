"""Evidence routes: list/detail, recapture, manual upload, artifact download, verify, PDF pack.

All evidence is restricted-access (signed-URL only) and every access is custody-logged.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.config import get_settings
from api.app.csam import ScanOutcome, scan_image
from api.app.images import InvalidImage, validate_and_load
from api.app.models.cases import Case
from api.app.models.csam import CsamSource
from api.app.models.evidence import CaptureKind, CaptureStatus, CustodyAction, EvidenceCapture
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import cases as cases_svc
from api.app.services import evidence as svc
from api.app.services.csam_incidents import record_incident
from api.app.storage.evidence import get_evidence_storage

router = APIRouter(prefix="/workspaces/{workspace_id}/cases/{case_id}", tags=["evidence"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)
_ADMIN = require_role(StaffRole.admin)


class CaptureOut(BaseModel):
    id: int
    kind: str
    status: str
    sensitive: bool
    requested_url: str | None
    final_url: str | None
    http_status: int | None
    page_title: str | None
    timestamp_status: str | None
    tsa_time: datetime | None
    manifest_sha256: str | None
    error: str | None
    capture_finished_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, c: EvidenceCapture) -> CaptureOut:
        return cls(
            id=c.id, kind=str(c.kind), status=str(c.status), sensitive=c.sensitive,
            requested_url=c.requested_url, final_url=c.final_url, http_status=c.http_status,
            page_title=c.page_title,
            timestamp_status=str(c.timestamp_status) if c.timestamp_status else None,
            tsa_time=c.tsa_time, manifest_sha256=c.manifest_sha256, error=c.error,
            capture_finished_at=c.capture_finished_at, created_at=c.created_at,
        )


class ArtifactOut(BaseModel):
    name: str
    sha256: str
    content_type: str
    size_bytes: int


class CustodyOut(BaseModel):
    action: str
    actor_staff_id: int | None
    reason: str | None
    detail: str | None
    created_at: datetime


class CaptureDetailOut(BaseModel):
    capture: CaptureOut
    artifacts: list[ArtifactOut]
    custody: list[CustodyOut]


class VerifyOut(BaseModel):
    ok: bool
    files: dict[str, bool]
    manifest_ok: bool
    timestamp_ok: bool | None


class DownloadResponse(BaseModel):
    url: str
    expires_in: int


def _case_or_404(session: Session, case_id: int) -> Case:
    case = cases_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return case


def _capture_or_404(session: Session, case_id: int, capture_id: int) -> EvidenceCapture:
    capture = svc.get_capture(session, capture_id)
    if capture is None or capture.case_id != case_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="capture not found")
    return capture


@router.get("/evidence", response_model=list[CaptureOut])
def list_evidence(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[CaptureOut]:
    _case_or_404(session, case_id)
    return [CaptureOut.of(c) for c in svc.list_captures(session, case_id)]


@router.post("/evidence/recapture", response_model=CaptureOut, status_code=status.HTTP_202_ACCEPTED)
def recapture(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaptureOut:
    case = _case_or_404(session, case_id)
    capture = svc.trigger_capture(
        session, workspace_id=workspace.id, case=case,
        kind=CaptureKind.recapture, actor_staff_id=staff.id,
    )
    return CaptureOut.of(capture)


@router.post("/evidence/upload", response_model=CaptureOut, status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    case_id: int,
    note: str = Form(..., min_length=1, max_length=2000),
    file: UploadFile = File(...),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaptureOut:
    case = _case_or_404(session, case_id)
    data = await file.read()
    if len(data) > get_settings().asset_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="file too large"
        )
    try:
        image = validate_and_load(data)  # Slice 3: sniff + full decode + bomb limits
    except InvalidImage as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG")  # canonical, sanitized PNG
    png = buf.getvalue()

    capture = svc.create_pending_capture(
        session, case=case, kind=CaptureKind.manual_upload,
        requested_url=case.source_url, captured_by_staff_id=staff.id,
    )
    # Durably burn the capture id BEFORE writing any write-once object, so a later failure can't
    # orphan sealed objects under a key a reused id would then collide with.
    session.commit()

    # CSAM scan choke point (CLAUDE.md #7): seal only on a `clean` result. A match → minimized
    # incident + nothing sealed; a scan error (incl. no scanner) → fail closed, nothing sealed.
    outcome = scan_image(png)
    if outcome is not ScanOutcome.clean:
        if outcome is ScanOutcome.match:
            record_incident(
                session, workspace_id=workspace.id, source=CsamSource.manual_upload,
                sha256=hashlib.sha256(png).hexdigest(), url=case.source_url, case_id=case.id,
            )
        capture.status = CaptureStatus.blocked
        capture.error = f"csam_{outcome}"
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="upload refused: content flagged by the CSAM scan (fail-closed)",
        )

    svc.seal_manual_upload(
        session, schema=workspace.schema_name, capture=capture,
        screenshot_png=png, attestation=note,
    )
    return CaptureOut.of(capture)


# Declared before /evidence/{capture_id} so "pack.pdf" isn't parsed as a capture id.
@router.get("/evidence/pack.pdf")
def evidence_pack(
    case_id: int,
    reason: str = Query(..., min_length=1, max_length=500),
    include_sensitive: bool = Query(default=False),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> Response:
    case = _case_or_404(session, case_id)
    pdf = svc.build_pack_pdf(
        session, schema=workspace.schema_name, case=case, actor_staff_id=staff.id,
        reason=reason, include_sensitive=include_sensitive,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="case-{case_id}-evidence.pdf"'},
    )


@router.get("/evidence/{capture_id}", response_model=CaptureDetailOut)
def get_evidence(
    case_id: int,
    capture_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> CaptureDetailOut:
    capture = _capture_or_404(session, case_id, capture_id)
    # Log the access to the (sensitive) capture metadata.
    svc.record_custody(
        session, case_id=case_id, capture_id=capture.id, action=CustodyAction.accessed,
        actor_staff_id=staff.id, detail="capture detail viewed",
    )
    return CaptureDetailOut(
        capture=CaptureOut.of(capture),
        artifacts=[
            ArtifactOut(name=a.name, sha256=a.sha256, content_type=a.content_type,
                        size_bytes=a.size_bytes)
            for a in svc.list_artifacts(session, capture_id)
        ],
        custody=[
            CustodyOut(action=str(e.action), actor_staff_id=e.actor_staff_id, reason=e.reason,
                       detail=e.detail, created_at=e.created_at)
            for e in svc.list_custody(session, case_id)
        ],
    )


@router.get("/evidence/{capture_id}/artifacts/{name}", response_model=DownloadResponse)
def download_artifact(
    case_id: int,
    capture_id: int,
    name: str,
    reason: str = Query(..., min_length=1, max_length=500),  # why (custody), required
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    capture = _capture_or_404(session, case_id, capture_id)
    artifact = next((a for a in svc.list_artifacts(session, capture_id) if a.name == name), None)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    ttl = get_settings().storage_signed_url_ttl_seconds
    url = get_evidence_storage().generate_download_url(
        artifact.object_key, filename=f"case{case_id}-{capture_id}-{name}", expires_in=ttl
    )
    svc.record_custody(
        session, case_id=case_id, capture_id=capture.id, action=CustodyAction.downloaded,
        actor_staff_id=staff.id, reason=reason, detail=name,
    )
    return DownloadResponse(url=url, expires_in=ttl)


@router.get("/evidence/{capture_id}/verify", response_model=VerifyOut)
def verify_evidence(
    case_id: int,
    capture_id: int,
    reason: str = Query(..., min_length=1, max_length=500),  # why (custody), required
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> VerifyOut:
    capture = _capture_or_404(session, case_id, capture_id)
    result = svc.verify_capture(
        session, schema=workspace.schema_name, capture=capture,
        actor_staff_id=staff.id, reason=reason,
    )
    return VerifyOut(
        ok=result.ok, files=result.files, manifest_ok=result.manifest_ok,
        timestamp_ok=result.timestamp_ok,
    )


