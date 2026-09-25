"""Tenant isolation for Slice 4 tables: settings, runs, candidates."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    DiscoverySettings,
    RunKind,
    RunStatus,
)
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"d-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        s.add(DiscoverySettings(monthly_call_budget=100 if tag == "A" else 200))
        run = DiscoveryRun(kind=RunKind.keyword, subject_id=subject.id, status=RunStatus.completed)
        s.add(run)
        s.flush()
        s.add(
            DiscoveryCandidate(
                subject_id=subject.id,
                run_id=run.id,
                provider="fake",
                kind=CandidateKind.link,
                source_url=f"https://found.example/{tag}",
                source_key=f"key-{tag}",
            )
        )


def test_discovery_tables_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        sources = set(s.scalars(select(DiscoveryCandidate.source_url)).all())
        budgets = set(s.scalars(select(DiscoverySettings.monthly_call_budget)).all())
    assert sources == {"https://found.example/B"}
    assert budgets == {200}
