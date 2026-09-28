"""Notice-template lookups and the counsel-approval lifecycle (Slice 8).

Templates are global public reference data. They ship `unapproved`; only an admin may mark one
`counsel_approved`, which records the approver on the row (the durable proof — audit_log is
tenant-scoped; see ADR 0011). Editing a body bumps the version and resets it to `unapproved`,
so an approved template can never be silently altered.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models.channels import NoticeTemplate, TemplateApproval
from api.app.services.notice_render import _TOKEN_RE, ALLOWED_FIELDS, NoticeRenderError

logger = logging.getLogger("visionguard.notices")


class TemplateNotFound(Exception):
    """No template for this claim type + method."""


class TemplateApprovalBlocked(Exception):
    """Approval refused: this claim type's send-time preconditions don't exist yet."""


# Claims whose matrix-required send-time preconditions are not yet implemented (identity
# verification — Phase 2 liveness/ID; see docs/legal/claims-matrix.md open questions). Approving
# their templates is refused so a counsel-approved template can never bypass a missing gate.
APPROVAL_BLOCKED_CLAIMS: frozenset[str] = frozenset({"likeness", "ncii", "impersonation"})


def get_template(session: Session, *, claim_type: str, method: str) -> NoticeTemplate:
    template = session.scalar(
        select(NoticeTemplate).where(
            NoticeTemplate.claim_type == claim_type,
            NoticeTemplate.method == method,
        )
    )
    if template is None:
        raise TemplateNotFound(f"no template for claim {claim_type!r} via {method!r}")
    return template


def list_templates(session: Session) -> list[NoticeTemplate]:
    return list(
        session.scalars(
            select(NoticeTemplate).order_by(NoticeTemplate.claim_type, NoticeTemplate.method)
        ).all()
    )


def get_template_by_id(session: Session, template_id: int) -> NoticeTemplate | None:
    return session.get(NoticeTemplate, template_id)


def _validate_template_body(*parts: str) -> None:
    """Reject a template that references a field outside the render whitelist, at edit time."""
    for part in parts:
        for match in _TOKEN_RE.finditer(part):
            if match.group(1) not in ALLOWED_FIELDS:
                raise NoticeRenderError(
                    f"template references unknown field {match.group(1)!r}"
                )


def approve_template(
    session: Session, *, template: NoticeTemplate, admin_staff_id: int, approver_name: str
) -> NoticeTemplate:
    """Admin-only: mark a template counsel-approved and record who + when on the row."""
    if template.claim_type in APPROVAL_BLOCKED_CLAIMS:
        raise TemplateApprovalBlocked(
            f"cannot approve a '{template.claim_type}' template yet: its send-time preconditions "
            "(identity verification) don't exist — blocked until identity verification ships "
            "(see docs/legal/claims-matrix.md open questions)"
        )
    template.approval_status = TemplateApproval.counsel_approved
    template.approved_by_staff_id = admin_staff_id
    template.approver_name = approver_name
    template.approved_at = datetime.now(UTC)
    session.flush()
    logger.info(
        "notice_template.approved id=%s claim=%s method=%s approver=%r by_staff=%s",
        template.id, template.claim_type, template.method, approver_name, admin_staff_id,
    )
    return template


def edit_template(
    session: Session,
    *,
    template: NoticeTemplate,
    name: str | None = None,
    subject_template: str | None = None,
    body_template: str | None = None,
) -> NoticeTemplate:
    """Edit a template: bump the version and RESET to unapproved (an approved template can never
    be silently altered)."""
    new_subject = subject_template if subject_template is not None else template.subject_template
    new_body = body_template if body_template is not None else template.body_template
    _validate_template_body(new_subject, new_body)
    if name is not None:
        template.name = name
    template.subject_template = new_subject
    template.body_template = new_body
    template.version += 1
    template.approval_status = TemplateApproval.unapproved
    template.approved_by_staff_id = None
    template.approver_name = None
    template.approved_at = None
    session.flush()
    logger.info(
        "notice_template.edited id=%s claim=%s method=%s new_version=%s (reset to unapproved)",
        template.id, template.claim_type, template.method, template.version,
    )
    return template
