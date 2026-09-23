"""Tenant isolation for the Slice 1 tables: subjects and allowlist_entries."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.subjects import AllowlistEntry, AllowlistKind, Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _two_fresh_workspaces(db: Fixtures) -> tuple:
    # Provision dedicated workspaces so the isolation writes don't pollute the shared ones.
    a = create_workspace_with_access(
        name="iso-a", creator_staff_id=db.admin_staff_id, slug=f"iso-a-{uuid.uuid4().hex[:8]}"
    )
    b = create_workspace_with_access(
        name="iso-b", creator_staff_id=db.admin_staff_id, slug=f"iso-b-{uuid.uuid4().hex[:8]}"
    )
    return a, b


def test_subjects_are_isolated_between_workspaces(db: Fixtures) -> None:
    a, b = _two_fresh_workspaces(db)
    with tenant_session(a.schema_name) as s:
        s.add(Subject(legal_name="iso-subject-A", handles=["a"]))
    with tenant_session(b.schema_name) as s:
        s.add(Subject(legal_name="iso-subject-B", handles=["b"]))

    with tenant_session(b.schema_name) as s:
        names = set(s.scalars(select(Subject.legal_name)).all())
    assert names == {"iso-subject-B"}


def test_allowlist_entries_are_isolated_between_workspaces(db: Fixtures) -> None:
    a, b = _two_fresh_workspaces(db)
    with tenant_session(a.schema_name) as s:
        s.add(AllowlistEntry(kind=AllowlistKind.domain, value="a-only.example"))
    with tenant_session(b.schema_name) as s:
        s.add(AllowlistEntry(kind=AllowlistKind.domain, value="b-only.example"))

    with tenant_session(a.schema_name) as s:
        values = set(s.scalars(select(AllowlistEntry.value)).all())
    assert values == {"a-only.example"}
