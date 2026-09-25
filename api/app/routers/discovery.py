"""Discovery routes: manual intake, scan trigger, candidates, runs, and settings."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.config import get_settings
from api.app.models.assets import Asset, AssetStatus
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    DiscoverySettings,
    ScanFrequency,
)
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.models.subjects import Subject
from api.app.services import discovery as svc
from api.app.services import subjects as subj_service
from api.app.services.discovery import DiscoveryNotAuthorized
from api.app.storage import get_storage

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["discovery"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)
_ADMIN = require_role(StaffRole.admin)


# ── Schemas ───────────────────────────────────────────────────────────────────


class IntakeIn(BaseModel):
    urls: list[str]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    provider: str | None
    subject_id: int
    asset_id: int | None
    query: str | None
    status: str
    calls_made: int
    estimated_cost_cents: int
    candidates_found: int
    started_at: datetime
    finished_at: datetime | None


class CandidateOut(BaseModel):
    id: int
    run_id: int | None
    provider: str
    query: str | None
    kind: CandidateKind
    source_url: str
    page_url: str | None
    sha256: str | None
    phash: str | None
    has_thumbnail: bool
    content_type: str | None
    discovered_at: datetime

    @classmethod
    def of(cls, c: DiscoveryCandidate) -> CandidateOut:
        return cls(
            id=c.id,
            run_id=c.run_id,
            provider=c.provider,
            query=c.query,
            kind=c.kind,
            source_url=c.source_url,
            page_url=c.page_url,
            sha256=c.sha256,
            phash=c.phash,
            has_thumbnail=c.thumbnail_key is not None,
            content_type=c.content_type,
            discovered_at=c.discovered_at,
        )


class ScanResult(BaseModel):
    enqueued: int


class DownloadResponse(BaseModel):
    url: str
    expires_in: int


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    monthly_call_budget: int
    scan_frequency: ScanFrequency
    tineye_enabled: bool
    thumbnail_retention_days: int


class SettingsIn(BaseModel):
    monthly_call_budget: int | None = None
    scan_frequency: ScanFrequency | None = None
    tineye_enabled: bool | None = None
    thumbnail_retention_days: int | None = None


def _subject_or_404(session: Session, subject_id: int) -> Subject:
    subject = subj_service.get_subject(session, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    return subject


# ── Subject-scoped discovery ──────────────────────────────────────────────────


@router.post("/subjects/{subject_id}/discovery/intake", response_model=RunOut)
def intake(
    subject_id: int,
    payload: IntakeIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DiscoveryRun:
    subject = _subject_or_404(session, subject_id)
    try:
        return svc.intake_urls(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            subject=subject,
            urls=payload.urls,
        )
    except DiscoveryNotAuthorized as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/subjects/{subject_id}/discovery/scan", response_model=ScanResult)
def scan(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> ScanResult:
    subject = _subject_or_404(session, subject_id)
    try:
        svc.assert_enforceable(session, subject)
    except DiscoveryNotAuthorized as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    ready_asset_ids = list(
        session.scalars(
            select(Asset.id).where(
                Asset.subject_id == subject_id, Asset.status == AssetStatus.ready
            )
        ).all()
    )
    from worker.discovery import keyword_scan, reverse_image_scan

    for asset_id in ready_asset_ids:
        reverse_image_scan.delay(workspace.id, subject_id, asset_id)
    keyword_scan.delay(workspace.id, subject_id)
    return ScanResult(enqueued=len(ready_asset_ids) + 1)


@router.get("/subjects/{subject_id}/discovery/candidates", response_model=list[CandidateOut])
def list_candidates(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[CandidateOut]:
    _subject_or_404(session, subject_id)
    return [CandidateOut.of(c) for c in svc.list_candidates(session, subject_id)]


@router.get(
    "/subjects/{subject_id}/discovery/candidates/{candidate_id}/thumbnail",
    response_model=DownloadResponse,
)
def candidate_thumbnail(
    subject_id: int,
    candidate_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    candidate = svc.get_candidate(session, candidate_id)
    if candidate is None or candidate.subject_id != subject_id or candidate.thumbnail_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no thumbnail")
    ttl = get_settings().storage_signed_url_ttl_seconds
    url = get_storage().generate_download_url(
        candidate.thumbnail_key, filename=f"candidate-{candidate.id}.jpg", expires_in=ttl
    )
    return DownloadResponse(url=url, expires_in=ttl)


@router.get("/subjects/{subject_id}/discovery/runs", response_model=list[RunOut])
def list_runs(
    subject_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[DiscoveryRun]:
    _subject_or_404(session, subject_id)
    return svc.list_runs(session, subject_id)


# ── Workspace-scoped settings ─────────────────────────────────────────────────


@router.get("/discovery/settings", response_model=SettingsOut)
def get_discovery_settings(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DiscoverySettings:
    return svc.get_or_create_settings(session)


@router.put("/discovery/settings", response_model=SettingsOut)
def update_discovery_settings(
    payload: SettingsIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> DiscoverySettings:
    settings = svc.get_or_create_settings(session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    session.flush()
    return settings
