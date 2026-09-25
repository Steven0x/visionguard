"""Review-inbox routes: queue, confirm, dismiss, reopen, bulk-dismiss, rescore, cases."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.config import get_settings
from api.app.models.assets import Asset
from api.app.models.discovery import CandidateKind, DiscoveryCandidate
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.models.review import Case, DismissReason
from api.app.models.subjects import Subject
from api.app.services import review as svc
from api.app.services import subjects as subj_service
from api.app.services.review import (
    CandidateAllowlisted,
    ClaimNotSupported,
    InvalidReason,
    NotEnforceable,
    ReviewConflict,
)
from api.app.services.scoring import rescore_candidates
from api.app.storage import get_storage

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["review"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)
_ADMIN = require_role(StaffRole.admin)


# ── Schemas ───────────────────────────────────────────────────────────────────


class InboxItemOut(BaseModel):
    id: int
    subject_id: int
    subject_name: str
    provider: str
    kind: CandidateKind
    source_url: str
    page_url: str | None
    score: int | None
    score_breakdown: dict | None
    best_match_asset_id: int | None
    has_found_thumbnail: bool
    has_asset_thumbnail: bool
    unverified: bool
    suggested_claim: str | None
    supported_claims: list[str]
    discovered_at: datetime

    @classmethod
    def of(cls, item: svc.InboxItem) -> InboxItemOut:
        c = item.candidate
        breakdown = c.score_breakdown or {}
        return cls(
            id=c.id,
            subject_id=c.subject_id,
            subject_name=item.subject.legal_name,
            provider=c.provider,
            kind=c.kind,
            source_url=c.source_url,
            page_url=c.page_url,
            score=c.score,
            score_breakdown=c.score_breakdown,
            best_match_asset_id=c.best_match_asset_id,
            has_found_thumbnail=c.thumbnail_key is not None,
            has_asset_thumbnail=c.best_match_asset_id is not None,
            unverified=bool(breakdown.get("unverified", c.kind == CandidateKind.link)),
            suggested_claim=item.suggested_claim,
            supported_claims=item.supported_claims,
            discovered_at=c.discovered_at,
        )


class ConfirmIn(BaseModel):
    claim_type: str


class DismissIn(BaseModel):
    reason: DismissReason


class ReopenIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


class BulkDismissIn(BaseModel):
    domain: str | None = None
    account: str | None = None
    reason: DismissReason
    dry_run: bool = True


class BulkDismissOut(BaseModel):
    count: int
    applied: bool


class RescoreIn(BaseModel):
    subject_id: int | None = None


class RescoreOut(BaseModel):
    rescored: int
    changed: list[int]


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    candidate_id: int | None
    matched_asset_id: int | None
    claim_type: str
    status: str
    created_at: datetime


class DownloadResponse(BaseModel):
    url: str
    expires_in: int


def _candidate_or_404(session: Session, candidate_id: int) -> DiscoveryCandidate:
    candidate = svc.get_candidate(session, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate not found")
    return candidate


def _subject_or_404(session: Session, subject_id: int) -> Subject:
    subject = subj_service.get_subject(session, subject_id)
    if subject is None:  # pragma: no cover - candidate FK guarantees the subject exists
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    return subject


# ── Inbox ─────────────────────────────────────────────────────────────────────


@router.get("/review/inbox", response_model=list[InboxItemOut])
def inbox(
    subject_id: int | None = None,
    min_score: int | None = Query(default=None, ge=0, le=100),
    provider: str | None = None,
    domain: str | None = None,
    kind: CandidateKind | None = None,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[InboxItemOut]:
    items = svc.list_inbox(
        session,
        subject_id=subject_id,
        min_score=min_score,
        provider=provider,
        domain=domain,
        kind=kind.value if kind else None,
    )
    return [InboxItemOut.of(i) for i in items]


@router.get("/review/cases", response_model=list[CaseOut])
def list_cases(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[Case]:
    return svc.list_cases(session)


# ── Decisions ─────────────────────────────────────────────────────────────────


@router.post(
    "/review/candidates/{candidate_id}/confirm",
    response_model=CaseOut,
    status_code=status.HTTP_201_CREATED,
)
def confirm(
    candidate_id: int,
    payload: ConfirmIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Case:
    candidate = _candidate_or_404(session, candidate_id)
    subject = _subject_or_404(session, candidate.subject_id)
    try:
        return svc.confirm_candidate(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            subject=subject,
            candidate=candidate,
            claim_type=payload.claim_type,
        )
    except NotEnforceable as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (ClaimNotSupported, CandidateAllowlisted) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/review/candidates/{candidate_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(
    candidate_id: int,
    payload: DismissIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> None:
    candidate = _candidate_or_404(session, candidate_id)
    try:
        svc.dismiss_candidate(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            candidate=candidate,
            reason=payload.reason.value,
        )
    except InvalidReason as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/review/candidates/{candidate_id}/reopen", status_code=status.HTTP_204_NO_CONTENT)
def reopen(
    candidate_id: int,
    payload: ReopenIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> None:
    candidate = _candidate_or_404(session, candidate_id)
    try:
        svc.reopen_candidate(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            candidate=candidate,
            note=payload.note,
        )
    except InvalidReason as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/review/bulk-dismiss", response_model=BulkDismissOut)
def bulk_dismiss(
    payload: BulkDismissIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> BulkDismissOut:
    try:
        result = svc.bulk_dismiss(
            session,
            workspace_id=workspace.id,
            actor_staff_id=staff.id,
            reason=payload.reason.value,
            domain=payload.domain,
            account=payload.account,
            dry_run=payload.dry_run,
        )
    except InvalidReason as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return BulkDismissOut(count=result.count, applied=result.applied)


@router.post("/review/rescore", response_model=RescoreOut)
def rescore(
    payload: RescoreIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> RescoreOut:
    result = rescore_candidates(session, subject_id=payload.subject_id)
    from api.app.audit.service import record_audit

    record_audit(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        action="review.rescore",
        entity_type="discovery_candidate",
        entity_id="*",
        # Record which candidates flipped status (e.g. auto_dismissed → pending, re-exposing a
        # previously-allowlisted source) so a rescore is reconstructable. Cap the list size.
        meta={
            "rescored": result.rescored,
            "changed_count": len(result.changed),
            "changed_ids": result.changed[:200],
        },
    )
    return RescoreOut(rescored=result.rescored, changed=result.changed)


# ── Thumbnails (signed URLs; not audited) ─────────────────────────────────────


def _signed(key: str, filename: str) -> DownloadResponse:
    ttl = get_settings().storage_signed_url_ttl_seconds
    url = get_storage().generate_download_url(key, filename=filename, expires_in=ttl)
    return DownloadResponse(url=url, expires_in=ttl)


@router.get(
    "/review/candidates/{candidate_id}/found-thumbnail", response_model=DownloadResponse
)
def found_thumbnail(
    candidate_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    candidate = _candidate_or_404(session, candidate_id)
    if candidate.thumbnail_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no thumbnail")
    return _signed(candidate.thumbnail_key, f"found-{candidate.id}.jpg")


@router.get(
    "/review/candidates/{candidate_id}/asset-thumbnail", response_model=DownloadResponse
)
def asset_thumbnail(
    candidate_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> DownloadResponse:
    candidate = _candidate_or_404(session, candidate_id)
    if candidate.best_match_asset_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no matched asset")
    asset = session.get(Asset, candidate.best_match_asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no matched asset")
    return _signed(asset.thumbnail_key, f"asset-{asset.id}.jpg")
