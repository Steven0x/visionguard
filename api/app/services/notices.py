"""Notice lifecycle service (Slice 8): the ONLY mutator of notices / notice_versions /
filing_log. Draft → edit → approve → send, with a hard send-time re-check (active authorization
+ supported claim + fresh sealed evidence + counsel-approved template + recorded human approval
+ completeness), all in the same transaction that records the send. The exact sent notice is
sealed write-once via the evidence machinery, and sending moves the case to Filed via the case
service. See docs/specs/notices.md."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.csam import ScanOutcome, scan_image
from api.app.email import EmailMessage, EmailSendError, get_email_backend
from api.app.models.cases import Case, CaseStatus
from api.app.models.channels import Channel, NoticeTemplate, TemplateApproval
from api.app.models.csam import CsamSource
from api.app.models.evidence import CaptureKind
from api.app.models.notices import FilingLog, FilingOutcome, Notice, NoticeStatus, NoticeVersion
from api.app.models.subjects import Subject
from api.app.notices_matrix import method_allowed_for_claim
from api.app.services import cases as cases_svc
from api.app.services import evidence as evidence_svc
from api.app.services.authorizations import active_authorization
from api.app.services.channels import get_channel, route_for
from api.app.services.claim_support import claim_support
from api.app.services.csam_incidents import record_incident
from api.app.services.notice_render import (
    build_context,
    missing_elements,
    now_utc,
    render,
    sanitize_header_value,
)
from api.app.services.scoring import urls_allowlisted
from api.app.services.templates import get_template, get_template_by_id

logger = logging.getLogger("visionguard.notices")


class NoticeStateError(Exception):
    """A notice operation is not allowed in the notice's current state."""


class NoticePreconditionFailed(Exception):
    """A send-time re-check failed (auth, claim, evidence, approval, completeness)."""


class CsamRefused(Exception):
    """A hand-submission screenshot was refused by the CSAM gate (fail-closed)."""


# ── Reads ─────────────────────────────────────────────────────────────────────


def get_notice_for_case(session: Session, case_id: int) -> Notice | None:
    """The current (non-withdrawn) notice for a case, if any."""
    return session.scalar(
        select(Notice)
        .where(Notice.case_id == case_id, Notice.status != NoticeStatus.withdrawn)
        .order_by(Notice.id.desc())
        .limit(1)
    )


def get_notice(session: Session, notice_id: int) -> Notice | None:
    return session.get(Notice, notice_id)


def list_versions(session: Session, notice_id: int) -> list[NoticeVersion]:
    return list(
        session.scalars(
            select(NoticeVersion)
            .where(NoticeVersion.notice_id == notice_id)
            .order_by(NoticeVersion.version)
        ).all()
    )


def _latest_version(session: Session, notice_id: int) -> NoticeVersion:
    version = session.scalar(
        select(NoticeVersion)
        .where(NoticeVersion.notice_id == notice_id)
        .order_by(NoticeVersion.version.desc())
        .limit(1)
    )
    if version is None:  # invariant: a notice always has ≥ 1 version
        raise NoticeStateError("notice has no versions")
    return version


def list_filing_log(session: Session, *, platform: str | None = None) -> list[FilingLog]:
    stmt = select(FilingLog).order_by(FilingLog.id.desc())
    if platform:
        stmt = stmt.where(FilingLog.platform == platform)
    return list(session.scalars(stmt).all())


# ── The send gate (non-raising) ─────────────────────────────────────────────────


def send_blockers(session: Session, *, notice: Notice, case: Case) -> list[str]:
    """Human-readable reasons the notice cannot be sent right now. Empty ⇒ sendable. This is the
    single source of truth for the send-time re-check; ``send``/``record_hand_submission`` refuse
    when it is non-empty, and the API surfaces it so staff see WHY (esp. 'template unapproved')."""
    blockers: list[str] = []
    if notice.status != NoticeStatus.draft:
        blockers.append("notice is not a draft")
    if CaseStatus(case.status) != CaseStatus.confirmed:
        blockers.append("case is not in Confirmed")
    if notice.claim_type != case.claim_type:
        blockers.append("claim changed since drafting; recreate the notice")

    subject = session.get(Subject, case.subject_id)
    if subject is None or active_authorization(session, subject.id) is None:
        blockers.append("no active agent authorization for the subject")
        subject = None
    else:
        supported = {c.claim_type for c in claim_support(session, subject) if c.supported}
        if notice.claim_type not in supported:
            blockers.append(
                f"claim '{notice.claim_type}' is no longer supported for this subject"
            )

    if not evidence_svc.has_fresh_sealed_capture(session, case.id):
        blockers.append("no fresh sealed evidence capture (recapture the page before filing)")

    # Allowlist re-check at send time (CLAUDE.md #8): a source allowlisted after the case opened
    # (a newly authorized reseller / the subject's own account) must not receive a takedown.
    # Check BOTH the source and the offender page URL, exactly as intake did — the matched image
    # is often on a CDN host while the allowlisted offender lives on the page URL.
    if urls_allowlisted(session, case.source_url, case.page_url):
        blockers.append(
            "target is now on the workspace allowlist; remove it from the allowlist or dismiss "
            "the case before sending"
        )

    # Fair-use consideration is required before a copyright filing (Lenz v. Universal); it is
    # recorded with the approval and reset by any edit.
    if case.claim_type == "copyright" and not notice.fair_use_considered:
        blockers.append(
            "fair use not considered — the approver must confirm fair-use consideration for a "
            "copyright notice"
        )

    # Defense-in-depth: re-check the claims matrix at send time so a channel row flipped to a
    # forbidden method (e.g. DMCA/email for trademark/likeness) after drafting can never send.
    if not method_allowed_for_claim(notice.claim_type, notice.method):
        blockers.append(
            f"channel method '{notice.method}' is not allowed for claim "
            f"'{notice.claim_type}' (claims matrix)"
        )

    template = get_template_by_id(session, notice.template_id)
    if template is None:
        blockers.append("template not found")
    elif template.approval_status != TemplateApproval.counsel_approved:
        blockers.append(
            "template is not counsel-approved (nothing can be sent until counsel signs off)"
        )

    if not (notice.approved_by_staff_id and notice.approved_at):
        blockers.append("notice has not been approved by a human")
    elif notice.approved_version != notice.current_version:
        blockers.append("notice was edited after approval; re-approve before sending")

    if subject is not None and template is not None:
        ctx = build_context(session, case=case, subject=subject, platform=notice.platform)
        required = list(template.required_elements or [])
        channel = get_channel(session, notice.channel_id)
        if channel and channel.required_fields:
            required += list(channel.required_fields)
        missing = missing_elements(required, ctx)
        if missing:
            blockers.append("draft is incomplete: missing " + ", ".join(sorted(set(missing))))
    return blockers


def _require_sendable(session: Session, *, notice: Notice, case: Case) -> None:
    blockers = send_blockers(session, notice=notice, case=case)
    if blockers:
        raise NoticePreconditionFailed("; ".join(blockers))


# ── Draft / edit / approve ──────────────────────────────────────────────────────


def create_draft(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    case: Case,
    platform: str,
) -> Notice:
    if CaseStatus(case.status) != CaseStatus.confirmed:
        raise NoticeStateError("a notice can only be drafted for a Confirmed case")
    # Only an ACTIVE notice blocks a new draft. A reopened case (Slice 9) still carries its prior
    # `sent`/`withdrawn` notice; that closed filing cycle must NOT carry its approval forward, so a
    # reopened Confirmed case drafts a fresh notice needing a fresh human approval.
    existing = get_notice_for_case(session, case.id)
    if existing is not None and existing.status in (
        NoticeStatus.draft, NoticeStatus.delivery_failed
    ):
        raise NoticeStateError("an active draft already exists for this case")

    channel: Channel = route_for(session, platform=platform, claim_type=case.claim_type)
    template: NoticeTemplate = get_template(
        session, claim_type=case.claim_type, method=str(channel.method)
    )
    subject = session.get(Subject, case.subject_id)
    if subject is None:
        raise NoticeStateError("case has no subject")

    ctx = build_context(session, case=case, subject=subject, platform=platform)
    rendered_subject = sanitize_header_value(render(template.subject_template, ctx))
    rendered_body = render(template.body_template, ctx)

    notice = Notice(
        case_id=case.id,
        channel_id=channel.id,
        template_id=template.id,
        template_version=template.version,
        claim_type=case.claim_type,
        method=str(channel.method),
        platform=platform,
        destination=channel.destination,
        status=NoticeStatus.draft,
        current_version=1,
        created_by_staff_id=actor_staff_id,
    )
    session.add(notice)
    session.flush()
    session.add(
        NoticeVersion(
            notice_id=notice.id, version=1, subject=rendered_subject, body=rendered_body,
            edited_by_staff_id=actor_staff_id,
        )
    )
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="notice.drafted", entity_type="notice", entity_id=str(notice.id),
        meta={"case_id": case.id, "platform": platform, "claim_type": case.claim_type,
              "method": str(channel.method)},
    )
    return notice


def edit_draft(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    notice: Notice,
    subject: str,
    body: str,
) -> Notice:
    if notice.status != NoticeStatus.draft:
        raise NoticeStateError("only a draft notice can be edited")
    new_version = notice.current_version + 1
    session.add(
        NoticeVersion(
            notice_id=notice.id, version=new_version,
            subject=sanitize_header_value(subject), body=body,
            edited_by_staff_id=actor_staff_id,
        )
    )
    notice.current_version = new_version
    # An edit invalidates the approval (the version binding blocks send until re-approval); clear
    # the fair-use tick too so it can never carry over to a later, different version.
    notice.fair_use_considered = False
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="notice.edited", entity_type="notice", entity_id=str(notice.id),
        meta={"version": new_version},
    )
    return notice


def approve(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    notice: Notice,
    fair_use_considered: bool = False,
) -> Notice:
    """Record a human approval on the notice (CLAUDE.md #3). This is necessary but not
    sufficient — send still re-checks the whole gate at send time. ``fair_use_considered`` is the
    approver's Lenz tick, required to send a copyright notice."""
    if notice.status != NoticeStatus.draft:
        raise NoticeStateError("only a draft notice can be approved")
    notice.approved_by_staff_id = actor_staff_id
    notice.approved_at = now_utc()
    # Bind the approval to the exact version approved. A later edit bumps current_version and this
    # stale binding blocks send until re-approved — so no one can approve v1 then send v2.
    notice.approved_version = notice.current_version
    notice.fair_use_considered = fair_use_considered
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="notice.approved", entity_type="notice", entity_id=str(notice.id),
        meta={"version": notice.current_version, "fair_use_considered": fair_use_considered},
    )
    return notice


def _apply_response_window(session: Session, *, case: Case, notice: Notice) -> None:
    """After filing, set the case follow-up timer to the platform's response window (Slice 9), so
    the case resurfaces on the follow-up list on the right cadence. Falls back to the generic
    ``filed`` timer the case transition already set when the channel has no window."""
    channel = get_channel(session, notice.channel_id)
    if channel is not None and channel.response_window_days:
        from datetime import UTC, datetime, timedelta

        case.due_at = datetime.now(UTC) + timedelta(days=channel.response_window_days)
        session.flush()


# ── Send (email) ────────────────────────────────────────────────────────────────


def send(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    schema: str,
    notice: Notice,
    case: Case,
) -> Notice:
    """Send an email-channel notice. Web-form/portal channels never send here — they produce a
    packet and are filed via ``record_hand_submission``."""
    if notice.method != "email":
        raise NoticeStateError(
            "this channel is not an email channel; use the packet + hand-submission flow"
        )
    _require_sendable(session, notice=notice, case=case)

    version = _latest_version(session, notice.id)
    subject_line = sanitize_header_value(version.subject)
    recipients = [sanitize_header_value(notice.destination)]
    from api.app.config import get_settings

    settings = get_settings()
    reply_to = sanitize_header_value(settings.email_reply_to) or None
    headers = {"From": sanitize_header_value(settings.email_from), "Subject": subject_line}
    if reply_to:
        headers["Reply-To"] = reply_to

    # Seal the EXACT bytes we will send BEFORE sending, so the immutable record always matches
    # what went out.
    capture = evidence_svc.create_pending_capture(
        session, case=case, kind=CaptureKind.notice,
        requested_url=notice.destination, captured_by_staff_id=actor_staff_id,
    )
    session.commit()  # burn the capture id before writing any write-once object
    evidence_svc.seal_notice_capture(
        session, schema=schema, capture=capture, notice_text=version.body,
        recipients=recipients, headers=headers, claim_type=notice.claim_type,
        template_id=notice.template_id, template_version=notice.template_version,
    )

    # Record the filing and move the case Confirmed → Filed, then COMMIT — so the send is durable
    # BEFORE we touch the network. The case transition re-checks the filing preconditions
    # atomically; if the case has concurrently left Confirmed this raises here and nothing is
    # sent. Committing first means a later transport failure can neither roll back the record nor
    # cause a duplicate outbound (the notice is no longer a draft, so a retry is refused).
    notice.status = NoticeStatus.sent
    notice.sealed_capture_id = capture.id
    notice.sent_by_staff_id = actor_staff_id
    notice.sent_at = now_utc()
    session.add(
        FilingLog(
            case_id=case.id, notice_id=notice.id, platform=notice.platform,
            claim_type=notice.claim_type, method=notice.method, outcome=FilingOutcome.sent,
            filed_by_staff_id=actor_staff_id,
        )
    )
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="notice.sent", entity_type="notice", entity_id=str(notice.id),
        meta={"case_id": case.id, "platform": notice.platform, "sealed_capture_id": capture.id},
    )
    cases_svc.transition(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id, case=case,
        to_status=CaseStatus.filed, reason="notice_sent",
    )
    _apply_response_window(session, case=case, notice=notice)
    session.commit()

    # Transport is the LAST step. On failure the send is already recorded (sealed artifact +
    # filing log + Filed case); flip the notice to a visible delivery_failed/retry state (the case
    # stays Filed) and surface the error. It will not double-send (a retry uses retry_send).
    message = EmailMessage(
        to=recipients, subject=subject_line, body=version.body,
        from_addr=sanitize_header_value(settings.email_from), reply_to=reply_to,
    )
    try:
        get_email_backend().send(message)
    except EmailSendError:
        notice.status = NoticeStatus.delivery_failed
        record_audit(
            session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
            action="notice.delivery_failed", entity_type="notice", entity_id=str(notice.id),
            meta={"case_id": case.id, "platform": notice.platform},
        )
        session.commit()
        raise
    return notice


def retry_send(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    notice: Notice,
) -> Notice:
    """Re-attempt transport for a notice whose delivery failed. The notice is already sealed and
    the case already Filed; this only retries the email and clears the delivery_failed state."""
    if notice.status != NoticeStatus.delivery_failed:
        raise NoticeStateError("only a delivery-failed notice can be retried")
    version = _latest_version(session, notice.id)
    subject_line = sanitize_header_value(version.subject)
    from api.app.config import get_settings

    settings = get_settings()
    reply_to = sanitize_header_value(settings.email_reply_to) or None
    from_addr = sanitize_header_value(settings.email_from)
    message = EmailMessage(
        to=[sanitize_header_value(notice.destination)], subject=subject_line,
        body=version.body, from_addr=from_addr, reply_to=reply_to,
    )
    get_email_backend().send(message)  # EmailSendError → still delivery_failed, caller 502
    notice.status = NoticeStatus.sent
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="notice.delivery_retried", entity_type="notice", entity_id=str(notice.id),
        meta={"case_id": notice.case_id, "platform": notice.platform},
    )
    return notice


# ── Web-form / portal: packet + hand-submission ──────────────────────────────────


def build_packet(session: Session, *, notice: Notice) -> dict:
    """A copy-ready packet + checklist for a web_form/portal channel. Read-only."""
    version = _latest_version(session, notice.id)
    channel = get_channel(session, notice.channel_id)
    required = list((channel.required_fields if channel else None) or [])
    return {
        "platform": notice.platform,
        "method": notice.method,
        "destination": notice.destination,
        "subject": version.subject,
        "body": version.body,
        "checklist": required,
        "instructions": (
            "Submit this at the destination URL as the authorized agent, then record the "
            "ticket number and a screenshot of the confirmation page."
        ),
    }


def record_hand_submission(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    schema: str,
    notice: Notice,
    case: Case,
    ticket_number: str,
    screenshot_png: bytes,
    subject_id: int | None,
) -> Notice:
    """File a web_form/portal notice submitted by hand: re-check the send gate, CSAM-scan + seal
    the confirmation screenshot (like manual evidence), log the filing, and move the case to
    Filed."""
    if notice.method == "email":
        raise NoticeStateError("email channels are filed via send(), not hand-submission")
    _require_sendable(session, notice=notice, case=case)

    capture = evidence_svc.create_pending_capture(
        session, case=case, kind=CaptureKind.manual_upload,
        requested_url=notice.destination, captured_by_staff_id=actor_staff_id,
    )
    session.commit()  # burn the capture id before any write-once object

    # CSAM choke point (CLAUDE.md #7): seal only on a `clean` result; a match records a minimized
    # incident, and a match/error fails closed with nothing sealed.
    outcome = scan_image(screenshot_png)
    if outcome is not ScanOutcome.clean:
        if outcome is ScanOutcome.match:
            record_incident(
                session, workspace_id=workspace_id, source=CsamSource.manual_upload,
                sha256=hashlib.sha256(screenshot_png).hexdigest(), url=notice.destination,
                subject_id=subject_id, case_id=case.id, actor_staff_id=actor_staff_id,
            )
        from api.app.models.evidence import CaptureStatus

        capture.status = CaptureStatus.blocked
        capture.error = f"csam_{outcome}"
        session.commit()
        raise CsamRefused("screenshot refused: content flagged by the CSAM scan (fail-closed)")

    evidence_svc.seal_manual_upload(
        session, schema=schema, capture=capture, screenshot_png=screenshot_png,
        attestation=f"hand-submission confirmation; ticket={ticket_number}",
    )

    notice.status = NoticeStatus.sent
    notice.sealed_capture_id = capture.id
    notice.sent_by_staff_id = actor_staff_id
    notice.sent_at = now_utc()
    session.add(
        FilingLog(
            case_id=case.id, notice_id=notice.id, platform=notice.platform,
            claim_type=notice.claim_type, method=notice.method,
            outcome=FilingOutcome.submitted_by_hand, ticket_number=ticket_number,
            filed_by_staff_id=actor_staff_id,
        )
    )
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="notice.hand_submitted", entity_type="notice", entity_id=str(notice.id),
        meta={"case_id": case.id, "platform": notice.platform, "ticket": ticket_number,
              "sealed_capture_id": capture.id},
    )
    cases_svc.transition(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id, case=case,
        to_status=CaseStatus.filed, reason="notice_hand_submitted",
    )
    _apply_response_window(session, case=case, notice=notice)
    return notice


# ── Withdraw ──────────────────────────────────────────────────────────────────────


def withdraw(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    notice: Notice,
    case: Case,
    note: str,
) -> Notice:
    """Retract a sent notice: move the case Filed → Withdrawn (note-gated by the case service),
    mark the notice withdrawn, and log the retraction. Correct a wrong claim by re-filing a new
    case from the same candidate via cases.refile."""
    if notice.status != NoticeStatus.sent:
        raise NoticeStateError("only a sent notice can be withdrawn")
    if not (note and note.strip()):
        raise NoticePreconditionFailed("withdrawing a filed notice requires a note")
    # The case service enforces Filed → Withdrawn and the note requirement + writes the case event.
    cases_svc.transition(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id, case=case,
        to_status=CaseStatus.withdrawn, reason="notice_withdrawn", note=note,
    )
    notice.status = NoticeStatus.withdrawn
    session.add(
        FilingLog(
            case_id=case.id, notice_id=notice.id, platform=notice.platform,
            claim_type=notice.claim_type, method=notice.method,
            outcome=FilingOutcome.withdrawn, response=note, filed_by_staff_id=actor_staff_id,
        )
    )
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="notice.withdrawn", entity_type="notice", entity_id=str(notice.id),
        meta={"case_id": case.id, "note": note},
    )
    return notice
