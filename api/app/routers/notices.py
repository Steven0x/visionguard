"""Notice routes (Slice 8): the per-case draft→approve→send flow, the web-form packet +
hand-submission, the filing log, and the admin-only global channel/template management.

Sending requires a recorded human approval and re-checks the whole gate at send time; nothing
can be sent while the template is unapproved (the whole claims matrix is still unapproved)."""

from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.app.auth.deps import (
    get_tenant_session,
    require_role,
    require_workspace_access,
)
from api.app.config import get_settings
from api.app.db.session import public_session
from api.app.email.backend import EmailSendError
from api.app.images import InvalidImage, validate_and_load
from api.app.models.cases import Case
from api.app.models.channels import NoticeTemplate
from api.app.models.notices import Notice
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import cases as cases_svc
from api.app.services import notices as svc
from api.app.services.channels import ChannelNotFound, MatrixViolation, list_channels
from api.app.services.notice_render import NoticeRenderError
from api.app.services.templates import (
    TemplateApprovalBlocked,
    TemplateNotFound,
    approve_template,
    edit_template,
    get_template_by_id,
    list_templates,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["notices"])
admin_router = APIRouter(tags=["notices-admin"])

_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)
_ADMIN = require_role(StaffRole.admin)


def _http(code: int, exc: Exception) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


# ── Schemas ──────────────────────────────────────────────────────────────────


class NoticeVersionOut(BaseModel):
    version: int
    subject: str
    body: str
    edited_by_staff_id: int | None
    created_at: datetime


class NoticeOut(BaseModel):
    id: int
    case_id: int
    platform: str
    method: str
    destination: str
    claim_type: str
    status: str
    current_version: int
    template_id: int
    template_version: int
    approved_by_staff_id: int | None
    approved_at: datetime | None
    sent_by_staff_id: int | None
    sent_at: datetime | None
    sealed_capture_id: int | None
    created_at: datetime

    @classmethod
    def of(cls, n: Notice) -> NoticeOut:
        return cls(
            id=n.id, case_id=n.case_id, platform=n.platform, method=str(n.method),
            destination=n.destination, claim_type=n.claim_type, status=str(n.status),
            current_version=n.current_version, template_id=n.template_id,
            template_version=n.template_version, approved_by_staff_id=n.approved_by_staff_id,
            approved_at=n.approved_at, sent_by_staff_id=n.sent_by_staff_id, sent_at=n.sent_at,
            sealed_capture_id=n.sealed_capture_id, created_at=n.created_at,
        )


class NoticeDetailOut(BaseModel):
    notice: NoticeOut | None
    versions: list[NoticeVersionOut]
    blockers: list[str]
    can_send: bool


class PacketOut(BaseModel):
    platform: str
    method: str
    destination: str
    subject: str
    body: str
    checklist: list[str]
    instructions: str


class CreateDraftIn(BaseModel):
    platform: str


class EditDraftIn(BaseModel):
    subject: str
    body: str


class ApproveIn(BaseModel):
    # The approver's Lenz tick — required to send a copyright notice.
    fair_use_considered: bool = False


class WithdrawIn(BaseModel):
    note: str


class FilingLogOut(BaseModel):
    id: int
    case_id: int
    notice_id: int | None
    platform: str
    claim_type: str
    method: str
    outcome: str
    ticket_number: str | None
    response: str | None
    filed_by_staff_id: int | None
    created_at: datetime


class ChannelOut(BaseModel):
    id: int
    platform: str
    claim_type: str
    method: str
    destination: str
    required_fields: list[str] | None
    active: bool


class TemplateOut(BaseModel):
    id: int
    claim_type: str
    method: str
    name: str
    subject_template: str
    body_template: str
    required_elements: list[str] | None
    approval_status: str
    approver_name: str | None
    approved_at: datetime | None
    version: int

    @classmethod
    def of(cls, t: NoticeTemplate) -> TemplateOut:
        return cls(
            id=t.id, claim_type=t.claim_type, method=str(t.method), name=t.name,
            subject_template=t.subject_template, body_template=t.body_template,
            required_elements=t.required_elements, approval_status=str(t.approval_status),
            approver_name=t.approver_name, approved_at=t.approved_at, version=t.version,
        )


class EditTemplateIn(BaseModel):
    name: str | None = None
    subject_template: str | None = None
    body_template: str | None = None


class ApproveTemplateIn(BaseModel):
    approver_name: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _case_or_404(session: Session, case_id: int) -> Case:
    case = cases_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return case


def _notice_or_404(session: Session, case_id: int) -> Notice:
    notice = svc.get_notice_for_case(session, case_id)
    if notice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no notice for case")
    return notice


def _detail(session: Session, case: Case, notice: Notice | None) -> NoticeDetailOut:
    if notice is None:
        return NoticeDetailOut(notice=None, versions=[], blockers=[], can_send=False)
    versions = [
        NoticeVersionOut(version=v.version, subject=v.subject, body=v.body,
                         edited_by_staff_id=v.edited_by_staff_id, created_at=v.created_at)
        for v in svc.list_versions(session, notice.id)
    ]
    blockers = svc.send_blockers(session, notice=notice, case=case)
    return NoticeDetailOut(
        notice=NoticeOut.of(notice), versions=versions, blockers=blockers,
        can_send=not blockers,
    )


# ── Per-case notice flow ─────────────────────────────────────────────────────


@router.get("/cases/{case_id}/notice", response_model=NoticeDetailOut)
def get_notice(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeDetailOut:
    case = _case_or_404(session, case_id)
    return _detail(session, case, svc.get_notice_for_case(session, case_id))


@router.post("/cases/{case_id}/notice", response_model=NoticeDetailOut,
             status_code=status.HTTP_201_CREATED)
def create_draft(
    case_id: int,
    payload: CreateDraftIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeDetailOut:
    case = _case_or_404(session, case_id)
    try:
        notice = svc.create_draft(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, case=case,
            platform=payload.platform,
        )
    except (ChannelNotFound, MatrixViolation, TemplateNotFound, NoticeRenderError) as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    except svc.NoticeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    return _detail(session, case, notice)


@router.put("/cases/{case_id}/notice", response_model=NoticeDetailOut)
def edit_draft(
    case_id: int,
    payload: EditDraftIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeDetailOut:
    case = _case_or_404(session, case_id)
    notice = _notice_or_404(session, case_id)
    try:
        svc.edit_draft(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, notice=notice,
            subject=payload.subject, body=payload.body,
        )
    except svc.NoticeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    return _detail(session, case, notice)


@router.post("/cases/{case_id}/notice/approve", response_model=NoticeDetailOut)
def approve_notice(
    case_id: int,
    payload: ApproveIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeDetailOut:
    case = _case_or_404(session, case_id)
    notice = _notice_or_404(session, case_id)
    try:
        svc.approve(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, notice=notice,
            fair_use_considered=payload.fair_use_considered,
        )
    except svc.NoticeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    return _detail(session, case, notice)


@router.post("/cases/{case_id}/notice/send", response_model=NoticeOut)
def send_notice(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeOut:
    case = _case_or_404(session, case_id)
    notice = _notice_or_404(session, case_id)
    try:
        svc.send(
            session, workspace_id=workspace.id, actor_staff_id=staff.id,
            schema=workspace.schema_name, notice=notice, case=case,
        )
    except svc.NoticePreconditionFailed as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    except svc.NoticeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    except EmailSendError as exc:
        raise _http(status.HTTP_502_BAD_GATEWAY, exc) from exc
    return NoticeOut.of(notice)


@router.post("/cases/{case_id}/notice/retry-send", response_model=NoticeOut)
def retry_send_notice(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeOut:
    _case_or_404(session, case_id)
    notice = _notice_or_404(session, case_id)
    try:
        svc.retry_send(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, notice=notice,
        )
    except svc.NoticeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    except EmailSendError as exc:
        raise _http(status.HTTP_502_BAD_GATEWAY, exc) from exc
    return NoticeOut.of(notice)


@router.get("/cases/{case_id}/notice/packet", response_model=PacketOut)
def notice_packet(
    case_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> PacketOut:
    _case_or_404(session, case_id)
    notice = _notice_or_404(session, case_id)
    if notice.method == "email":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email channels are sent, not submitted by hand; there is no packet",
        )
    return PacketOut(**svc.build_packet(session, notice=notice))


@router.post("/cases/{case_id}/notice/hand-submission", response_model=NoticeOut,
             status_code=status.HTTP_201_CREATED)
async def record_hand_submission(
    case_id: int,
    ticket_number: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeOut:
    case = _case_or_404(session, case_id)
    notice = _notice_or_404(session, case_id)
    data = await file.read()
    if len(data) > get_settings().asset_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="file too large"
        )
    try:
        image = validate_and_load(data)
    except InvalidImage as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG")  # canonical, sanitized PNG
    png = buf.getvalue()
    try:
        svc.record_hand_submission(
            session, workspace_id=workspace.id, actor_staff_id=staff.id,
            schema=workspace.schema_name, notice=notice, case=case,
            ticket_number=ticket_number, screenshot_png=png, subject_id=case.subject_id,
        )
    except svc.NoticePreconditionFailed as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    except svc.NoticeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    except svc.CsamRefused as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    return NoticeOut.of(notice)


@router.post("/cases/{case_id}/notice/withdraw", response_model=NoticeOut)
def withdraw_notice(
    case_id: int,
    payload: WithdrawIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> NoticeOut:
    case = _case_or_404(session, case_id)
    notice = _notice_or_404(session, case_id)
    try:
        svc.withdraw(
            session, workspace_id=workspace.id, actor_staff_id=staff.id, notice=notice,
            case=case, note=payload.note,
        )
    except svc.NoticePreconditionFailed as exc:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
    except svc.NoticeStateError as exc:
        raise _http(status.HTTP_409_CONFLICT, exc) from exc
    return NoticeOut.of(notice)


@router.get("/filing-log", response_model=list[FilingLogOut])
def filing_log(
    platform: str | None = Query(default=None),
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list[FilingLogOut]:
    return [
        FilingLogOut(
            id=f.id, case_id=f.case_id, notice_id=f.notice_id, platform=f.platform,
            claim_type=f.claim_type, method=f.method, outcome=str(f.outcome),
            ticket_number=f.ticket_number, response=f.response,
            filed_by_staff_id=f.filed_by_staff_id, created_at=f.created_at,
        )
        for f in svc.list_filing_log(session, platform=platform)
    ]


# ── Admin: global channel + template management (public reference data) ──────────


@admin_router.get("/channels", response_model=list[ChannelOut], tags=["notices-admin"])
def get_channels(staff: Staff = Depends(_ADMIN)) -> list[ChannelOut]:
    with public_session() as session:
        return [
            ChannelOut(
                id=c.id, platform=c.platform, claim_type=c.claim_type, method=str(c.method),
                destination=c.destination, required_fields=c.required_fields, active=c.active,
            )
            for c in list_channels(session)
        ]


@admin_router.get("/notice-templates", response_model=list[TemplateOut], tags=["notices-admin"])
def get_templates(staff: Staff = Depends(_ADMIN)) -> list[TemplateOut]:
    with public_session() as session:
        return [TemplateOut.of(t) for t in list_templates(session)]


@admin_router.put("/notice-templates/{template_id}", response_model=TemplateOut,
                  tags=["notices-admin"])
def put_template(
    template_id: int, payload: EditTemplateIn, staff: Staff = Depends(_ADMIN)
) -> TemplateOut:
    with public_session() as session:
        template = get_template_by_id(session, template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
        try:
            edit_template(
                session, template=template, name=payload.name,
                subject_template=payload.subject_template, body_template=payload.body_template,
            )
        except NoticeRenderError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return TemplateOut.of(template)


@admin_router.post("/notice-templates/{template_id}/approve", response_model=TemplateOut,
                   tags=["notices-admin"])
def approve_notice_template(
    template_id: int, payload: ApproveTemplateIn, staff: Staff = Depends(_ADMIN)
) -> TemplateOut:
    with public_session() as session:
        template = get_template_by_id(session, template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
        try:
            approve_template(
                session, template=template, admin_staff_id=staff.id,
                approver_name=payload.approver_name,
            )
        except TemplateApprovalBlocked as exc:
            raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, exc) from exc
        return TemplateOut.of(template)
