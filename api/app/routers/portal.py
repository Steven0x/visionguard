"""Agency customer portal (Slice 12). All routes resolve the agency's ONE workspace from its
membership (get_agency_session) — never from the URL — and return minimized, portal-safe data.
Only two writes exist (URL tip, "Needs from you" answer); both create staff-review work and never
auto-confirm. Every write and report download is audited with the agency user id.

Default-deny: staff routes reject the agency role elsewhere; this router is the ONLY agency
surface. See docs/specs/portal.md."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.auth.deps import (
    AgencyContext,
    get_agency_context,
    get_agency_session,
    get_tenant_session,
    require_role,
    require_workspace_access,
)
from api.app.config import get_settings
from api.app.models.cases import Case
from api.app.models.portal import PortalSubmission, SubmissionStatus
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.models.subjects import Subject
from api.app.services import documents
from api.app.services import portal as svc
from api.app.services import reports as reports_svc
from api.app.services.discovery import DiscoveryNotAuthorized, intake_urls
from api.app.services.portal import PdfImageScanBlocked, TipRateLimited
from api.app.uploads import (
    UnsupportedFileType,
    UploadTooLarge,
    read_capped_upload,
    require_document_type,
    sanitize_filename,
)

router = APIRouter(prefix="/portal", tags=["portal"])


# ── Context ─────────────────────────────────────────────────────────────────────
class PortalContext(BaseModel):
    email: str
    role: str
    workspace_id: int
    workspace_name: str


@router.get("/context", response_model=PortalContext)
def context(ctx: AgencyContext = Depends(get_agency_context)) -> PortalContext:
    return PortalContext(
        email=ctx.staff.email,
        role=str(ctx.staff.role),
        workspace_id=ctx.workspace.id,
        workspace_name=ctx.workspace.name,
    )


# ── Reads ─────────────────────────────────────────────────────────────────────
@router.get("/subjects", response_model=list[svc.PortalSubject])
def list_subjects(session: Session = Depends(get_agency_session)) -> list[svc.PortalSubject]:
    return svc.list_subjects(session)


@router.get("/cases", response_model=list[svc.PortalCase])
def list_cases(session: Session = Depends(get_agency_session)) -> list[svc.PortalCase]:
    return svc.list_cases(session)


@router.get("/cases/{case_id}", response_model=svc.PortalCaseDetail)
def case_detail(
    case_id: int, session: Session = Depends(get_agency_session)
) -> svc.PortalCaseDetail:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return svc.case_detail(session, case)


@router.get("/reports", response_model=list[svc.PortalReport])
def list_reports(session: Session = Depends(get_agency_session)) -> list[svc.PortalReport]:
    return [svc.portal_report(r) for r in reports_svc.list_reports(session)]


@router.get("/reports/{report_id}.pdf")
def download_report(
    report_id: int,
    ctx: AgencyContext = Depends(get_agency_context),
    session: Session = Depends(get_agency_session),
) -> Response:
    report = reports_svc.get_report(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    data, media_type = reports_svc.read_artifact(report, which="pdf")
    record_audit(
        session,
        workspace_id=ctx.workspace.id,
        actor_staff_id=ctx.staff.id,
        action="report.downloaded",
        entity_type="report",
        entity_id=str(report.id),
        meta={"artifact": "pdf", "portal": True},
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="report-{report.id}.pdf"'},
    )


@router.get("/needs", response_model=list[svc.PortalNeed])
def list_needs(session: Session = Depends(get_agency_session)) -> list[svc.PortalNeed]:
    return svc.needs_items(session)


# ── Writes ──────────────────────────────────────────────────────────────────────
def _subject_or_404(session: Session, subject_id: int) -> Subject:
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subject not found")
    return subject


class TipIn(BaseModel):
    subject_id: int
    url: str


class TipOut(BaseModel):
    submission_id: int
    candidate_created: bool
    detail: str


@router.post("/tips", response_model=TipOut, status_code=status.HTTP_201_CREATED)
def submit_tip(
    payload: TipIn,
    ctx: AgencyContext = Depends(get_agency_context),
    session: Session = Depends(get_agency_session),
) -> TipOut:
    subject = _subject_or_404(session, payload.subject_id)
    # Daily cap on top of the per-minute write rate limit.
    try:
        svc.enforce_tip_cap(session, staff_id=ctx.staff.id)
    except TipRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc

    submission = svc.record_tip(
        session,
        workspace_id=ctx.workspace.id,
        staff_id=ctx.staff.id,
        subject_id=subject.id,
        url=payload.url,
    )
    # Route the tip into manual intake as a PENDING candidate for staff review (never auto-confirm).
    # If the subject isn't enforceable yet, the tip is still recorded for staff.
    candidate_created = True
    detail = "Tip received and queued for staff review."
    try:
        intake_urls(
            session,
            workspace_id=ctx.workspace.id,
            actor_staff_id=ctx.staff.id,
            subject=subject,
            urls=[payload.url],
        )
    except DiscoveryNotAuthorized:
        candidate_created = False
        detail = "Tip received; it will be reviewed once this subject is authorized."
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return TipOut(submission_id=submission.id, candidate_created=candidate_created, detail=detail)


class NeedsAnswerOut(BaseModel):
    submission_id: int
    detail: str


@router.post("/needs/answer", response_model=NeedsAnswerOut, status_code=status.HTTP_201_CREATED)
async def answer_needs(
    subject_id: int = Form(...),
    need_type: str = Form(...),
    body: str | None = Form(None),
    file: UploadFile | None = File(None),
    ctx: AgencyContext = Depends(get_agency_context),
    session: Session = Depends(get_agency_session),
) -> NeedsAnswerOut:
    subject = _subject_or_404(session, subject_id)
    if need_type not in svc.NEED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"need_type must be one of: {', '.join(sorted(svc.NEED_TYPES))}",
        )
    has_body = bool(body and body.strip())
    if file is None and not has_body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide a text answer or a document",
        )

    file_data: bytes | None = None
    content_type: str | None = None
    file_name: str | None = None
    if file is not None:
        try:
            file_data = await read_capped_upload(file, get_settings().storage_max_upload_bytes)
            content_type = require_document_type(file_data)
        except (UploadTooLarge, UnsupportedFileType) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        if content_type != "application/pdf":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="only PDF documents are accepted",
            )
        # First outsider-uploaded file: scan every embedded image before storing anything.
        try:
            svc.scan_pdf_images(
                schema=ctx.workspace.schema_name,
                workspace_id=ctx.workspace.id,
                actor_staff_id=ctx.staff.id,
                subject_id=subject.id,
                data=file_data,
            )
        except PdfImageScanBlocked as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        file_name = sanitize_filename(file.filename)

    submission = svc.record_needs_answer(
        session,
        workspace_id=ctx.workspace.id,
        schema=ctx.workspace.schema_name,
        staff_id=ctx.staff.id,
        subject_id=subject.id,
        need_type=need_type,
        body=body if has_body else None,
        file_data=file_data,
        file_content_type=content_type,
        file_name=file_name,
    )
    return NeedsAnswerOut(submission_id=submission.id, detail="Answer received for staff review.")


# ── Staff-side review of portal submissions (staff only) ─────────────────────────
staff_router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["portal-staff"])
_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)


class SubmissionOut(BaseModel):
    id: int
    kind: str
    subject_id: int | None
    need_type: str | None
    body: str | None
    url: str | None
    file_name: str | None
    status: str
    submitted_by_staff_id: int
    created_at: str

    @classmethod
    def of(cls, s: PortalSubmission) -> SubmissionOut:
        return cls(
            id=s.id,
            kind=str(s.kind),
            subject_id=s.subject_id,
            need_type=s.need_type,
            body=s.body,
            url=s.url,
            file_name=s.file_name,
            status=str(s.status),
            submitted_by_staff_id=s.submitted_by_staff_id,
            created_at=s.created_at.isoformat(),
        )


class ReviewIn(BaseModel):
    status: SubmissionStatus


@staff_router.get("/submissions", response_model=list[SubmissionOut])
def list_submissions(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[SubmissionOut]:
    return [SubmissionOut.of(s) for s in svc.list_submissions(session)]


def _submission_or_404(session: Session, submission_id: int) -> PortalSubmission:
    submission = svc.get_submission(session, submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission not found")
    return submission


@staff_router.post("/submissions/{submission_id}/review", response_model=SubmissionOut)
def review_submission(
    submission_id: int,
    payload: ReviewIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> SubmissionOut:
    submission = _submission_or_404(session, submission_id)
    updated = svc.review_submission(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        submission=submission,
        status=payload.status,
    )
    return SubmissionOut.of(updated)


class SubmissionFileOut(BaseModel):
    url: str


@staff_router.get("/submissions/{submission_id}/file", response_model=SubmissionFileOut)
def download_submission_file(
    submission_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> SubmissionFileOut:
    """A short-lived signed URL to the quarantined PDF — staff download only, never inline."""
    submission = _submission_or_404(session, submission_id)
    if not submission.file_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="submission has no file"
        )
    url = documents.signed_download_url(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        entity_type="portal_submission",
        entity_id=submission.id,
        file_key=submission.file_key,
        file_name=submission.file_name or "submission.pdf",
    )
    return SubmissionFileOut(url=url)
