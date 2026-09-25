"""Asset (reference image) and keyword routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.config import get_settings
from api.app.images import InvalidImage
from api.app.models.assets import Asset, AssetStatus, SubjectKeyword
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import assets as asset_service
from api.app.services import keywords as keyword_service
from api.app.services import subjects as subj_service
from api.app.services.assets import AssetDeletionBlocked
from api.app.services.documents import signed_download_url
from api.app.storage import get_storage
from api.app.uploads import (
    UnsupportedFileType,
    UploadTooLarge,
    read_capped_upload,
    require_image_type,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/subjects/{subject_id}", tags=["assets"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    file_name: str
    content_type: str
    size_bytes: int
    status: AssetStatus
    sha256: str | None
    phash: str | None
    duplicate_of_asset_id: int | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime


class DownloadResponse(BaseModel):
    url: str
    expires_in: int


class KeywordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str


class KeywordIn(BaseModel):
    keyword: str


class IdentifiersResponse(BaseModel):
    identifiers: list[str]


def _require_subject(session: Session, subject_id: int) -> None:
    if subj_service.get_subject(session, subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")


def _asset_or_404(session: Session, subject_id: int, asset_id: int) -> Asset:
    asset = asset_service.get_asset(session, asset_id)
    if asset is None or asset.subject_id != subject_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return asset


# ── Assets ────────────────────────────────────────────────────────────────────


@router.get("/assets", response_model=list[AssetOut])
def list_assets(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[Asset]:
    _require_subject(session, subject_id)
    return asset_service.list_assets(session, subject_id)


@router.post("/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    subject_id: int,
    file: UploadFile = File(...),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Asset:
    _require_subject(session, subject_id)
    try:
        data = await read_capped_upload(file, get_settings().asset_max_upload_bytes)
        content_type = require_image_type(data)
        return asset_service.create_asset(
            session,
            workspace_id=workspace.id,
            schema=workspace.schema_name,
            actor_staff_id=staff.id,
            subject_id=subject_id,
            data=data,
            content_type=content_type,
            file_name=file.filename or "upload",
        )
    except (UploadTooLarge, UnsupportedFileType, InvalidImage) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    subject_id: int,
    asset_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> None:
    asset = _asset_or_404(session, subject_id, asset_id)
    try:
        asset_service.delete_asset(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, asset=asset
        )
    except AssetDeletionBlocked as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/retry", response_model=AssetOut)
def retry_asset(
    subject_id: int,
    asset_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Asset:
    asset = _asset_or_404(session, subject_id, asset_id)
    if not asset_service.retry_asset(
        session, workspace_id=workspace.id, actor_staff_id=staff.id, asset=asset
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="asset is not failed or has hit the retry limit",
        )
    return asset


@router.get("/assets/{asset_id}/thumbnail", response_model=DownloadResponse)
def thumbnail_url(
    subject_id: int,
    asset_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    asset = _asset_or_404(session, subject_id, asset_id)
    ttl = get_settings().storage_signed_url_ttl_seconds
    # Thumbnails aren't evidence — not audited (gallery polling would flood the log).
    url = get_storage().generate_download_url(
        asset.thumbnail_key, filename=f"{asset.id}-thumb.jpg", expires_in=ttl
    )
    return DownloadResponse(url=url, expires_in=ttl)


@router.get("/assets/{asset_id}/original", response_model=DownloadResponse)
def original_url(
    subject_id: int,
    asset_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    asset = _asset_or_404(session, subject_id, asset_id)
    ttl = get_settings().storage_signed_url_ttl_seconds
    url = signed_download_url(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        entity_type="asset",
        entity_id=asset.id,
        file_key=asset.file_key,
        file_name=asset.file_name,
    )
    return DownloadResponse(url=url, expires_in=ttl)


# ── Keywords / identifiers ────────────────────────────────────────────────────


@router.get("/keywords", response_model=list[KeywordOut])
def list_keywords(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[SubjectKeyword]:
    _require_subject(session, subject_id)
    return keyword_service.list_keywords(session, subject_id)


@router.post("/keywords", response_model=KeywordOut, status_code=status.HTTP_201_CREATED)
def add_keyword(
    subject_id: int,
    payload: KeywordIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> SubjectKeyword:
    _require_subject(session, subject_id)
    try:
        return keyword_service.add_keyword(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            subject_id=subject_id,
            keyword=payload.keyword,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.delete("/keywords/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_keyword(
    subject_id: int,
    keyword_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> None:
    record = keyword_service.get_keyword(session, keyword_id)
    if record is None or record.subject_id != subject_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="keyword not found")
    keyword_service.remove_keyword(
        session, workspace_id=workspace.id, actor_staff_id=staff.id, record=record
    )


@router.get("/identifiers", response_model=IdentifiersResponse)
def get_identifiers(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> IdentifiersResponse:
    subject = subj_service.get_subject(session, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    return IdentifiersResponse(identifiers=keyword_service.identifiers(session, subject))
