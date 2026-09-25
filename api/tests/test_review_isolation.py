"""Tenant isolation for Slice 5 tables: cases and review_decisions."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.review import (
    Case,
    CaseStatus,
    ReviewDecision,
    ReviewDecisionKind,
)
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"r-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        s.add(
            Case(
                subject_id=subject.id,
                claim_type=f"claim-{tag}",
                status=CaseStatus.confirmed,
            )
        )
        s.add(
            ReviewDecision(
                subject_id=subject.id,
                decision=ReviewDecisionKind.dismiss,
                reason=f"reason-{tag}",
            )
        )


def test_review_tables_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        claims = set(s.scalars(select(Case.claim_type)).all())
        reasons = set(s.scalars(select(ReviewDecision.reason)).all())
    assert claims == {"claim-B"}
    assert reasons == {"reason-B"}
