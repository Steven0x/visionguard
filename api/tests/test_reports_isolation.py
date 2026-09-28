"""Tenant isolation for the Slice 10 `reports` table (and the `discovery_candidates.shown_at`
column). A report generated for workspace A must never be visible from workspace B."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.reports import Report
from api.app.services import reports as reports_svc
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures
from api.tests.reviewhelpers import make_subject


def _fresh(db: Fixtures):
    slug = f"r-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed_report(ws, staff_id: int) -> str:
    """Generate a report and return its globally-unique pdf_key (per-schema id sequences mean the
    row id alone can't distinguish two workspaces — both may be id=1)."""
    schema = ws.schema_name
    subject = make_subject(schema)
    with tenant_session(schema) as s:
        report = reports_svc.generate_report(
            s, schema=schema, workspace_id=ws.id, subject_id=subject,
            start=date(2026, 1, 1), end=date(2026, 1, 31), actor_staff_id=staff_id,
        )
        return report.pdf_key


def test_reports_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    a_key = _seed_report(a, db.admin_staff_id)
    b_key = _seed_report(b, db.admin_staff_id)
    assert a_key != b_key

    with tenant_session(b.schema_name) as s:
        keys = set(s.scalars(select(Report.pdf_key)).all())
    # B sees only its own report; A's is unreachable from B's schema.
    assert keys == {b_key}
    assert a_key not in keys
