"""Tenant isolation + append-only guarantees for Slice 9 tables: notice_outcomes, url_rechecks."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from api.app.db.session import get_engine, tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.notices import Notice, NoticeStatus
from api.app.models.outcomes import NoticeOutcome, OutcomeKind, RecheckResult, UrlRecheck
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"o-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        case = Case(subject_id=subject.id, claim_type="copyright", status=CaseStatus.filed)
        s.add(case)
        s.flush()
        notice = Notice(
            case_id=case.id, channel_id=1, template_id=1, template_version=1,
            claim_type="copyright", method="email", platform="generic_host",
            destination="a@b.invalid", status=NoticeStatus.sent,
        )
        s.add(notice)
        s.flush()
        s.add(
            NoticeOutcome(
                case_id=case.id, notice_id=notice.id, outcome=OutcomeKind.removed,
                effective_at=date(2026, 1, 1), note=f"outcome-{tag}",
            )
        )
        s.add(
            UrlRecheck(
                case_id=case.id, probed_url=f"https://x-{tag}.example/p",
                result=RecheckResult.gone, http_status=404,
            )
        )


def test_outcomes_and_rechecks_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        notes = set(s.scalars(select(NoticeOutcome.note)).all())
        urls = set(s.scalars(select(UrlRecheck.probed_url)).all())
    assert notes == {"outcome-B"}
    assert urls == {"https://x-B.example/p"}


def test_notice_outcomes_and_rechecks_are_append_only(db: Fixtures) -> None:
    schema = db.workspace_a.schema_name
    _seed(schema, "immutable")

    engine = get_engine()
    # Use a real column per table so the failure is the append-only TRIGGER, not a parse error.
    updates = {
        "notice_outcomes": "note = 'tampered'",
        "url_rechecks": "detail = 'tampered'",
    }
    with engine.connect() as conn:
        for table, set_clause in updates.items():
            with pytest.raises(DBAPIError):
                conn.execute(text(f'UPDATE "{schema}".{table} SET {set_clause}'))
            conn.rollback()
            with pytest.raises(DBAPIError):
                conn.execute(text(f'DELETE FROM "{schema}".{table}'))
            conn.rollback()
