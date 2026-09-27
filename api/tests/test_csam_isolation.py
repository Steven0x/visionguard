"""Tenant isolation for the csam_incidents table (CLAUDE.md #5)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.csam import CsamIncident, CsamSource
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"i-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def test_csam_incidents_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    with tenant_session(a.schema_name) as s:
        s.add(CsamIncident(source=CsamSource.discovery, sha256="a" * 64, url="https://a.example"))
    with tenant_session(b.schema_name) as s:
        s.add(CsamIncident(source=CsamSource.capture, sha256="b" * 64, url="https://b.example"))

    with tenant_session(b.schema_name) as s:
        rows = list(s.scalars(select(CsamIncident)))
    assert len(rows) == 1
    assert rows[0].sha256 == "b" * 64 and rows[0].url == "https://b.example"
