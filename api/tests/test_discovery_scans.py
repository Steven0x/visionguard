"""Reverse-image and keyword scans (fake provider + fake fetcher)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from worker.discovery import keyword_scan, reverse_image_scan

from api.app.db.session import tenant_session
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    RunKind,
    RunStatus,
)
from api.app.models.rights import ConsentRecord, ConsentType, RecordStatus
from api.app.models.subjects import Subject
from api.tests.discohelpers import authorized_subject


def _grant_biometrics(schema: str, subject_id: int) -> None:
    with tenant_session(schema) as s:
        subject = s.get(Subject, subject_id)
        assert subject is not None
        subject.biometrics_blocked = False
        s.add(
            ConsentRecord(
                subject_id=subject_id, type=ConsentType.biometric, file_key="k",
                file_name="c.pdf", content_type="application/pdf", signer_name="x",
                signed_date=date(2026, 1, 1), status=RecordStatus.active,
            )
        )


def test_reverse_scan_stores_fingerprints_and_thumbnail(db, new_workspace):
    sid, aid = authorized_subject(new_workspace.schema_name, ready_asset=True)
    _grant_biometrics(new_workspace.schema_name, sid)  # embedding is biometric-gated (CLAUDE.md #1)
    assert reverse_image_scan.run(new_workspace.id, sid, aid) == "completed"

    with tenant_session(new_workspace.schema_name) as s:
        candidate = s.scalar(
            select(DiscoveryCandidate).where(DiscoveryCandidate.kind == CandidateKind.image)
        )
        assert candidate is not None
        assert candidate.sha256 and candidate.phash and candidate.thumbnail_key
        assert candidate.embedding is not None
        run = s.scalar(
            select(DiscoveryRun).where(DiscoveryRun.kind == RunKind.reverse_image)
        )
        assert run.status == RunStatus.completed
        assert run.candidates_found >= 1


def test_reverse_scan_dedupes_on_rerun(db, new_workspace):
    sid, aid = authorized_subject(new_workspace.schema_name, ready_asset=True)
    reverse_image_scan.run(new_workspace.id, sid, aid)
    reverse_image_scan.run(new_workspace.id, sid, aid)  # same source_url → no new candidate
    with tenant_session(new_workspace.schema_name) as s:
        count = s.scalar(select(func.count()).select_from(DiscoveryCandidate))
    assert count == 1


def test_keyword_scan_creates_link_candidates(db, new_workspace):
    # A non-risky keyword: risky terms are suppressed in safe mode (no real CSAM scanner).
    sid, _ = authorized_subject(new_workspace.schema_name, keywords=("starlet",))
    assert keyword_scan.run(new_workspace.id, sid) == "completed"
    with tenant_session(new_workspace.schema_name) as s:
        links = list(
            s.scalars(
                select(DiscoveryCandidate).where(
                    DiscoveryCandidate.kind == CandidateKind.link
                )
            ).all()
        )
    assert links and all(c.kind == CandidateKind.link for c in links)
    assert any(c.query == "starlet" and c.source == "keyword" for c in links)
