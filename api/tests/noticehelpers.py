"""Helpers for Slice 8 notice tests: copyright rights, template approval state, and a
confirmed+evidenced case ready to file."""

from __future__ import annotations

from api.app.db.session import public_session, tenant_session
from api.app.models.cases import CaseStatus
from api.app.models.channels import NoticeTemplate, TemplateApproval
from api.app.models.rights import RightsRecord, RightsStatus, RightsType

from .casehelpers import make_case, seal_capture
from .reviewhelpers import make_subject


def add_copyright_rights(schema: str, subject_id: int) -> int:
    """A self-owned-declaration rights record → the subject supports the `copyright` claim."""
    with tenant_session(schema) as session:
        record = RightsRecord(
            subject_id=subject_id,
            type=RightsType.self_owned_declaration,
            file_key="k",
            file_name="own.pdf",
            content_type="application/pdf",
            status=RightsStatus.active,
        )
        session.add(record)
        session.flush()
        return record.id


def set_template_approval(
    claim_type: str, method: str, *, approved: bool, approver: str = "Counsel"
) -> None:
    """Force a template's approval state so a test is deterministic regardless of order (templates
    are global public reference data shared across the session)."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    with public_session() as session:
        row = session.scalar(
            select(NoticeTemplate).where(
                NoticeTemplate.claim_type == claim_type, NoticeTemplate.method == method
            )
        )
        assert row is not None, f"seed template missing for {claim_type}/{method}"
        if approved:
            row.approval_status = TemplateApproval.counsel_approved
            row.approved_by_staff_id = 1
            row.approver_name = approver
            row.approved_at = datetime.now(UTC)
        else:
            row.approval_status = TemplateApproval.unapproved
            row.approved_by_staff_id = None
            row.approver_name = None
            row.approved_at = None


def confirmed_copyright_case(schema: str, *, source_url: str = "https://leak.example/p/1") -> int:
    """A Confirmed copyright case with a fresh sealed page capture — ready to file."""
    subject_id = make_subject(schema, authorized=True)
    add_copyright_rights(schema, subject_id)
    case_id = make_case(
        schema, subject_id, status=CaseStatus.confirmed, claim_type="copyright",
        source_url=source_url,
    )
    seal_capture(schema, case_id)
    return case_id
