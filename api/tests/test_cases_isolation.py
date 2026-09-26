"""Tenant isolation for Slice 6 tables: case_events and case_notes."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseEvent, CaseEventKind, CaseNote, CaseStatus
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"c-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        case = Case(subject_id=subject.id, claim_type=f"claim-{tag}", status=CaseStatus.confirmed)
        s.add(case)
        s.flush()
        s.add(
            CaseEvent(
                case_id=case.id, kind=CaseEventKind.transition,
                from_status="confirmed", to_status=f"to-{tag}",
            )
        )
        s.add(CaseNote(case_id=case.id, body=f"note-{tag}"))


def test_case_events_and_notes_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        to_states = set(s.scalars(select(CaseEvent.to_status)).all())
        notes = set(s.scalars(select(CaseNote.body)).all())
    assert to_states == {"to-B"}
    assert notes == {"note-B"}
