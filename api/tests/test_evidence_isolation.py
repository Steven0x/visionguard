"""Tenant isolation for Slice 7 tables: evidence_captures, evidence_artifacts, custody_events."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.evidence import (
    CaptureKind,
    CaptureStatus,
    CustodyAction,
    CustodyEvent,
    EvidenceArtifact,
    EvidenceCapture,
)
from api.app.models.subjects import Subject
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures


def _fresh(db: Fixtures):
    slug = f"e-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _seed(schema: str, tag: str) -> None:
    with tenant_session(schema) as s:
        subject = Subject(legal_name=f"subj-{tag}")
        s.add(subject)
        s.flush()
        case = Case(subject_id=subject.id, claim_type="likeness", status=CaseStatus.confirmed)
        s.add(case)
        s.flush()
        capture = EvidenceCapture(
            case_id=case.id, kind=CaptureKind.auto, status=CaptureStatus.sealed,
            manifest_sha256=f"{tag}-manifest",
        )
        s.add(capture)
        s.flush()
        s.add(
            EvidenceArtifact(
                capture_id=capture.id, name="screenshot.png", object_key=f"{schema}/e/{tag}",
                sha256=f"{tag}-sha", content_type="image/png", size_bytes=1,
            )
        )
        s.add(
            CustodyEvent(
                case_id=case.id, capture_id=capture.id, action=CustodyAction.captured,
                detail=f"detail-{tag}",
            )
        )


def test_evidence_tables_isolated(db: Fixtures) -> None:
    a = _fresh(db)
    b = _fresh(db)
    _seed(a.schema_name, "A")
    _seed(b.schema_name, "B")

    with tenant_session(b.schema_name) as s:
        manifests = set(s.scalars(select(EvidenceCapture.manifest_sha256)).all())
        keys = set(s.scalars(select(EvidenceArtifact.object_key)).all())
        details = set(s.scalars(select(CustodyEvent.detail)).all())
    assert manifests == {"B-manifest"}
    assert keys == {f"{b.schema_name}/e/B"}
    assert details == {"detail-B"}
