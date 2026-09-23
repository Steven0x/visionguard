"""Tenant isolation for the Slice 1 tables: subjects and allowlist_entries."""

from __future__ import annotations

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.subjects import AllowlistEntry, AllowlistKind, Subject
from api.tests.conftest import Fixtures


def test_subjects_are_isolated_between_workspaces(db: Fixtures) -> None:
    with tenant_session(db.workspace_a.schema_name) as s:
        s.add(Subject(legal_name="iso-subject-A", handles=["a"]))
    with tenant_session(db.workspace_b.schema_name) as s:
        s.add(Subject(legal_name="iso-subject-B", handles=["b"]))

    with tenant_session(db.workspace_b.schema_name) as s:
        names = set(s.scalars(select(Subject.legal_name)).all())
    assert "iso-subject-B" in names
    assert "iso-subject-A" not in names


def test_allowlist_entries_are_isolated_between_workspaces(db: Fixtures) -> None:
    with tenant_session(db.workspace_a.schema_name) as s:
        s.add(AllowlistEntry(kind=AllowlistKind.domain, value="a-only.example"))
    with tenant_session(db.workspace_b.schema_name) as s:
        s.add(AllowlistEntry(kind=AllowlistKind.domain, value="b-only.example"))

    with tenant_session(db.workspace_a.schema_name) as s:
        values = set(s.scalars(select(AllowlistEntry.value)).all())
    assert "a-only.example" in values
    assert "b-only.example" not in values
