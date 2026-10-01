"""Tenant isolation for the portal_submissions table (Slice 12, CLAUDE.md #5)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.portal import PortalSubmission, SubmissionKind
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"ps-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def test_portal_submissions_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    with tenant_session(a.schema_name) as s:
        s.add(
            PortalSubmission(
                kind=SubmissionKind.url_tip, url="https://a.example", submitted_by_staff_id=1
            )
        )
    with tenant_session(b.schema_name) as s:
        s.add(
            PortalSubmission(
                kind=SubmissionKind.needs_response,
                need_type="missing_authorization",
                body="b answer",
                submitted_by_staff_id=2,
            )
        )

    with tenant_session(b.schema_name) as s:
        rows = list(s.scalars(select(PortalSubmission)))
    assert len(rows) == 1
    assert rows[0].body == "b answer" and rows[0].url is None
