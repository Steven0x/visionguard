"""Agency-portal service: minimized read serializers (all minimization lives HERE, one place)
and the two agency write actions (URL tip, "Needs from you" answer). No counting of its own —
reuses metrics/reports/discovery/documents/csam.

Minimization rules (CLAUDE.md #7, docs/specs/portal.md):
- No image reference is ever returned for any case.
- ``display_url`` is domain-only for an ncii OR sensitive case; the full URL otherwise.
- Case timelines expose transitions only (no actor, reason, or note); notes are never exposed.
- Reports/subjects/cases drop internal fields (staff ids, keys, hashes, internal timestamps).
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.csam import ScanOutcome, scan_image
from api.app.models.cases import Case, CaseEvent, CaseEventKind
from api.app.models.csam import CsamSource
from api.app.models.portal import PortalSubmission, SubmissionKind, SubmissionStatus
from api.app.models.reports import Report
from api.app.models.subjects import Subject
from api.app.services import documents
from api.app.services.csam_incidents import record_incident
from api.app.services.metrics import _needs_from_you

# Cap embedded-image extraction so a crafted PDF can't exhaust the worker.
_MAX_PDF_IMAGES = 100

# Human labels for the derived "Needs from you" buckets.
_NEED_LABELS = {
    "missing_authorization": "Agent authorization document",
    "ownership_rights": "Proof of ownership (photographer contact, license, or registration)",
    "enforcement_consent": "Signed enforcement consent",
}
# The only need types an agency may answer (what GET /portal/needs can surface).
NEED_TYPES = frozenset(_NEED_LABELS)


class PdfImageScanBlocked(Exception):
    """An embedded image in an uploaded PDF failed the CSAM scan (fail closed)."""


class TipRateLimited(Exception):
    """The agency user hit its per-day URL-tip cap."""


# ── Read DTOs (portal-safe) ─────────────────────────────────────────────────────
class PortalSubject(BaseModel):
    id: int
    legal_name: str
    stage_names: list[str]
    handles: list[str]
    status: str


class PortalCase(BaseModel):
    id: int
    subject_id: int
    claim_type: str
    status: str
    display_url: str | None
    created_at: datetime
    updated_at: datetime


class PortalTimelineEvent(BaseModel):
    from_status: str | None
    to_status: str | None
    created_at: datetime


class PortalCaseDetail(BaseModel):
    case: PortalCase
    timeline: list[PortalTimelineEvent]


class PortalReport(BaseModel):
    id: int
    subject_id: int | None
    period_start: date
    period_end: date
    created_at: datetime


class PortalNeed(BaseModel):
    subject_id: int
    subject_name: str
    need_type: str
    label: str


class PortalSubmissionOut(BaseModel):
    id: int
    kind: str
    subject_id: int | None
    need_type: str | None
    status: str
    created_at: datetime


def _display_url(case: Case) -> str | None:
    """Domain-only for an ncii or sensitive case; the full source URL otherwise; never an image.

    The reduced form is rebuilt from the host (+ non-default port) only — never the raw netloc —
    so any userinfo (``user@host``) can't ride along and misrepresent the domain.
    """
    if not case.source_url:
        return None
    if case.claim_type == "ncii" or case.sensitive:
        parts = urlsplit(case.source_url)
        if not parts.scheme or not parts.hostname:
            return None
        authority = parts.hostname
        if parts.port is not None:
            authority = f"{authority}:{parts.port}"
        return f"{parts.scheme}://{authority}"
    return case.source_url


def portal_subject(subject: Subject) -> PortalSubject:
    return PortalSubject(
        id=subject.id,
        legal_name=subject.legal_name,
        stage_names=list(subject.stage_names),
        handles=list(subject.handles),
        status=str(subject.status),
    )


def portal_case(case: Case) -> PortalCase:
    return PortalCase(
        id=case.id,
        subject_id=case.subject_id,
        claim_type=case.claim_type,
        status=str(case.status),
        display_url=_display_url(case),
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def list_subjects(session: Session) -> list[PortalSubject]:
    rows = session.scalars(select(Subject).order_by(Subject.id)).all()
    return [portal_subject(s) for s in rows]


def list_cases(session: Session) -> list[PortalCase]:
    rows = session.scalars(select(Case).order_by(Case.id.desc())).all()
    return [portal_case(c) for c in rows]


def case_detail(session: Session, case: Case) -> PortalCaseDetail:
    events = session.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.id, CaseEvent.kind == CaseEventKind.transition)
        .order_by(CaseEvent.id)
    ).all()
    timeline = [
        PortalTimelineEvent(
            from_status=e.from_status, to_status=e.to_status, created_at=e.created_at
        )
        for e in events
    ]
    return PortalCaseDetail(case=portal_case(case), timeline=timeline)


def portal_report(report: Report) -> PortalReport:
    return PortalReport(
        id=report.id,
        subject_id=report.subject_id,
        period_start=report.period_start,
        period_end=report.period_end,
        created_at=report.created_at,
    )


def needs_items(session: Session) -> list[PortalNeed]:
    """One item per (subject, unblocking need) for the whole workspace, derived from claim support
    (reuses metrics._needs_from_you — no new counting). The date range only affects the licensed
    count we don't use here, so any range works."""
    needs = _needs_from_you(session, subject_id=None, start=date(2000, 1, 1), end=date.today())
    buckets = {
        "missing_authorization": needs.missing_authorization,
        "ownership_rights": needs.ownership_rights,
        "enforcement_consent": needs.enforcement_consent,
    }
    names = {
        s.id: s.legal_name
        for s in session.scalars(select(Subject)).all()
    }
    items: list[PortalNeed] = []
    for need_type, subject_ids in buckets.items():
        for sid in subject_ids:
            items.append(
                PortalNeed(
                    subject_id=sid,
                    subject_name=names.get(sid, f"subject {sid}"),
                    need_type=need_type,
                    label=_NEED_LABELS[need_type],
                )
            )
    return items


# ── PDF embedded-image CSAM scan (outsider upload) ───────────────────────────────
def scan_pdf_images(
    *,
    schema: str,
    workspace_id: int,
    actor_staff_id: int,
    subject_id: int | None,
    data: bytes,
) -> None:
    """Extract every *extractable* embedded image from an uploaded PDF and CSAM-scan it. Fail
    closed: a `match` records a minimized incident and raises; a scan `error` or an unparseable
    PDF also raises. Stores nothing on any non-clean path.

    A match is recorded on its OWN committed tenant session so the incident survives the request's
    rollback (the caller rejects the submission with a 422). No image bytes are ever stored.

    Defense-in-depth note: this scans the images pypdf can enumerate; the stored file is also kept
    under a quarantine prefix and is never rendered inline (staff attachment download only), so an
    image an extractor misses still can't auto-render to anyone.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        images = [img for page in reader.pages for img in page.images]
    except Exception:  # noqa: BLE001 - a PDF we can't parse fails closed
        raise PdfImageScanBlocked("could not read the PDF to scan embedded images") from None

    if len(images) > _MAX_PDF_IMAGES:
        raise PdfImageScanBlocked("too many embedded images in the PDF")

    for img in images:
        img_bytes = img.data
        outcome = scan_image(img_bytes)
        if outcome is ScanOutcome.clean:
            continue
        if outcome is ScanOutcome.match:
            # Independent session so the incident is committed even though we then reject.
            from api.app.db.session import tenant_session

            with tenant_session(schema) as incident_session:
                record_incident(
                    incident_session,
                    workspace_id=workspace_id,
                    source=CsamSource.portal_upload,
                    sha256=hashlib.sha256(img_bytes).hexdigest(),
                    url=None,
                    subject_id=subject_id,
                    actor_staff_id=actor_staff_id,
                )
        raise PdfImageScanBlocked("an embedded image failed the CSAM scan; nothing was stored")


# ── Submissions (agency writes) ──────────────────────────────────────────────────
def _tips_today(session: Session, *, staff_id: int) -> int:
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        session.scalar(
            select(func.count())
            .select_from(PortalSubmission)
            .where(
                PortalSubmission.kind == SubmissionKind.url_tip,
                PortalSubmission.submitted_by_staff_id == staff_id,
                PortalSubmission.created_at >= midnight,
            )
        )
        or 0
    )


def enforce_tip_cap(session: Session, *, staff_id: int) -> None:
    cap = get_settings().portal_tip_daily_cap
    if _tips_today(session, staff_id=staff_id) >= cap:
        raise TipRateLimited(
            f"daily URL-tip limit reached ({cap}/day). Please try again tomorrow."
        )


def record_tip(
    session: Session,
    *,
    workspace_id: int,
    staff_id: int,
    subject_id: int,
    url: str,
) -> PortalSubmission:
    submission = PortalSubmission(
        kind=SubmissionKind.url_tip,
        subject_id=subject_id,
        url=url,
        submitted_by_staff_id=staff_id,
    )
    session.add(submission)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=staff_id,
        action="portal.tip_submitted",
        entity_type="portal_submission",
        entity_id=str(submission.id),
    )
    return submission


def record_needs_answer(
    session: Session,
    *,
    workspace_id: int,
    schema: str,
    staff_id: int,
    subject_id: int,
    need_type: str,
    body: str | None,
    file_data: bytes | None,
    file_content_type: str | None,
    file_name: str | None,
) -> PortalSubmission:
    """Persist a "Needs from you" answer for staff review. The PDF (if any) has already been
    validated + CSAM-scanned by the caller; store it under the quarantine prefix."""
    file_key: str | None = None
    if file_data is not None and file_content_type is not None:
        file_key = documents.store_document(schema, "needs_response", file_data, file_content_type)
    submission = PortalSubmission(
        kind=SubmissionKind.needs_response,
        subject_id=subject_id,
        need_type=need_type,
        body=body,
        file_key=file_key,
        file_name=file_name,
        submitted_by_staff_id=staff_id,
    )
    session.add(submission)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=staff_id,
        action="portal.needs_answered",
        entity_type="portal_submission",
        entity_id=str(submission.id),
        meta={"need_type": need_type, "has_file": file_key is not None},
    )
    return submission


# ── Staff-side review ─────────────────────────────────────────────────────────────
def list_submissions(session: Session) -> list[PortalSubmission]:
    return list(
        session.scalars(
            select(PortalSubmission).order_by(PortalSubmission.id.desc())
        ).all()
    )


def get_submission(session: Session, submission_id: int) -> PortalSubmission | None:
    return session.get(PortalSubmission, submission_id)


def review_submission(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int,
    submission: PortalSubmission,
    status: SubmissionStatus,
) -> PortalSubmission:
    submission.status = status
    submission.reviewed_by_staff_id = actor_staff_id
    submission.reviewed_at = datetime.now(UTC)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="portal.submission_reviewed",
        entity_type="portal_submission",
        entity_id=str(submission.id),
        meta={"status": str(status)},
    )
    return submission
