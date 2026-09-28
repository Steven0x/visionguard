"""Tenant isolation for Slice 8 tables: notices, notice_versions, filing_log."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.notices import (
    FilingLog,
    FilingOutcome,
    Notice,
    NoticeStatus,
    NoticeVersion,
)
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"n-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        case = Case(subject_id=subject.id, claim_type="copyright", status=CaseStatus.confirmed)
        s.add(case)
        s.flush()
        notice = Notice(
            case_id=case.id, channel_id=1, template_id=1, template_version=1,
            claim_type="copyright", method="email", platform=f"plat-{tag}",
            destination=f"abuse-{tag}@example.invalid", status=NoticeStatus.draft,
        )
        s.add(notice)
        s.flush()
        s.add(
            NoticeVersion(notice_id=notice.id, version=1, subject=f"sub-{tag}", body=f"body-{tag}")
        )
        s.add(
            FilingLog(
                case_id=case.id, notice_id=notice.id, platform=f"plat-{tag}",
                claim_type="copyright", method="email", outcome=FilingOutcome.sent,
            )
        )


def test_notices_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        platforms = set(s.scalars(select(Notice.platform)).all())
        bodies = set(s.scalars(select(NoticeVersion.body)).all())
        log_platforms = set(s.scalars(select(FilingLog.platform)).all())
    assert platforms == {"plat-B"}
    assert bodies == {"body-B"}
    assert log_platforms == {"plat-B"}
