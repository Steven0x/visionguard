"""Tenant isolation for the Slice 2 tables: rights, consent, agent authorizations."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.rights import (
    AgentAuthorization,
    ConsentRecord,
    ConsentType,
    RightsRecord,
    RightsType,
)
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"r-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(
        name=slug, creator_staff_id=db.admin_staff_id, slug=slug
    )


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        s.add(
            RightsRecord(
                subject_id=subject.id,
                type=RightsType.self_owned_declaration,
                file_key=f"{schema}/rights/x",
                file_name="d.pdf",
                content_type="application/pdf",
            )
        )
        s.add(
            ConsentRecord(
                subject_id=subject.id,
                type=ConsentType.enforcement,
                file_key=f"{schema}/consent/x",
                file_name="c.pdf",
                content_type="application/pdf",
                signer_name=f"signer-{tag}",
                signed_date=date(2026, 1, 1),
            )
        )
        s.add(
            AgentAuthorization(
                subject_id=None,
                signer_name=f"auth-{tag}",
                authorized_date=date(2026, 1, 1),
            )
        )


def test_rights_consent_authorizations_are_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        signers = set(s.scalars(select(ConsentRecord.signer_name)).all())
        auth_signers = set(s.scalars(select(AgentAuthorization.signer_name)).all())
        subjects = set(s.scalars(select(Subject.legal_name)).all())
    assert signers == {"signer-B"}
    assert auth_signers == {"auth-B"}
    assert subjects == {"subj-B"}
