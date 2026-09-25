"""Tenant isolation for the Slice 3 tables: assets and subject_keywords."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.assets import Asset, AssetStatus, SubjectKeyword
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"a-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        s.add(
            Asset(
                subject_id=subject.id,
                file_key=f"{schema}/asset/{tag}",
                thumbnail_key=f"{schema}/thumb/{tag}",
                file_name="a.png",
                content_type="image/png",
                size_bytes=1,
                status=AssetStatus.ready,
                sha256=f"sha-{tag}",
            )
        )
        s.add(SubjectKeyword(subject_id=subject.id, keyword=f"kw-{tag}"))


def test_assets_and_keywords_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        shas = set(s.scalars(select(Asset.sha256)).all())
        kws = set(s.scalars(select(SubjectKeyword.keyword)).all())
    assert shas == {"sha-B"}
    assert kws == {"kw-B"}
