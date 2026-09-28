"""Reports & internal-metrics routes (Slice 10): generate an agency PDF report (per workspace or
per subject, over a date range), list/download prior reports (audited), and the per-workspace
internal metrics summary. Nothing is sent automatically — staff generate, review and download."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import metrics as metrics_svc
from api.app.services import reports as svc

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["reports"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)


# ── Schemas ───────────────────────────────────────────────────────────────────


class GenerateReportIn(BaseModel):
    subject_id: int | None = None
    start: date
    end: date
    include_thumbnails: bool = False


class ReportOut(BaseModel):
    id: int
    subject_id: int | None
    period_start: date
    period_end: date
    as_of: datetime
    include_thumbnails: bool
    pdf_sha256: str
    json_sha256: str
    generated_by_staff_id: int | None
    created_at: datetime


class ProviderCostOut(BaseModel):
    provider: str
    cost_cents: int


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


class MetricsSummaryOut(BaseModel):
    removals: list[MetricOut]
    review_precision: float | None
    wrong_filing_rate: float | None
    re_upload_rate: float | None
    review_minutes_per_case: float | None
    provider_cost: list[ProviderCostOut]
    provider_cost_total_cents: int


def _report_or_404(session: Session, report_id: int) -> svc.Report:
    report = svc.get_report(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return report


# ── Reports ─────────────────────────────────────────────────────────────────


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def generate_report(
    payload: GenerateReportIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> ReportOut:
    try:
        report = svc.generate_report(
            session, schema=workspace.schema_name, workspace_id=workspace.id,
            subject_id=payload.subject_id, start=payload.start, end=payload.end,
            actor_staff_id=staff.id, include_thumbnails=payload.include_thumbnails,
        )
    except svc.ReportSubjectNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.ReportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ReportOut.model_validate(report, from_attributes=True)


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    subject_id: int | None = Query(default=None),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[ReportOut]:
    return [
        ReportOut.model_validate(r, from_attributes=True)
        for r in svc.list_reports(session, subject_id=subject_id)
    ]


@router.get("/reports/{report_id}.pdf")
def download_report_pdf(
    report_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Response:
    report = _report_or_404(session, report_id)
    data, media_type = svc.read_artifact(report, which="pdf")
    record_audit(
        session, workspace_id=workspace.id, actor_staff_id=staff.id,
        action="report.downloaded", entity_type="report", entity_id=str(report.id),
        meta={"artifact": "pdf"},
    )
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="report-{report.id}.pdf"'},
    )


@router.get("/reports/{report_id}/inputs.json")
def download_report_inputs(
    report_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> Response:
    report = _report_or_404(session, report_id)
    data, media_type = svc.read_artifact(report, which="json")
    record_audit(
        session, workspace_id=workspace.id, actor_staff_id=staff.id,
        action="report.downloaded", entity_type="report", entity_id=str(report.id),
        meta={"artifact": "json"},
    )
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="report-{report.id}-inputs.json"'},
    )


# ── Internal metrics summary (per workspace, staff-only) ──────────────────────


@router.get("/metrics/summary", response_model=MetricsSummaryOut)
def metrics_summary(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> MetricsSummaryOut:
    s = metrics_svc.metrics_summary(session)
    return MetricsSummaryOut(
        removals=[
            MetricOut(
                platform=m.platform, claim_type=m.claim_type, filed=m.filed,
                withdrawn=m.withdrawn, removed=m.removed, removed_verified=m.removed_verified,
                removed_staff_only=m.removed_staff_only, pending=m.pending,
                removal_rate=m.removal_rate, median_days_to_removal=m.median_days_to_removal,
            )
            for m in s.removals
        ],
        review_precision=s.review_precision,
        wrong_filing_rate=s.wrong_filing_rate,
        re_upload_rate=s.re_upload_rate,
        review_minutes_per_case=s.review_minutes_per_case,
        provider_cost=[
            ProviderCostOut(provider=pc.provider, cost_cents=pc.cost_cents)
            for pc in s.provider_cost
        ],
        provider_cost_total_cents=s.provider_cost_total_cents,
    )
