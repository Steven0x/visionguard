"""Reverse-image and keyword scans (fake provider + fake fetcher)."""

from __future__ import annotations

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
from api.tests.discohelpers import authorized_subject


def test_reverse_scan_stores_fingerprints_and_thumbnail(db, new_workspace):
    sid, aid = authorized_subject(new_workspace.schema_name, ready_asset=True)
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
    sid, _ = authorized_subject(new_workspace.schema_name, keywords=("leaked",))
    assert keyword_scan.run(new_workspace.id, sid) == "completed"
    with tenant_session(new_workspace.schema_name) as s:
        links = list(
            s.scalars(
                select(DiscoveryCandidate).where(
                    DiscoveryCandidate.kind == CandidateKind.link
                )
            ).all()
        )
    assert links and all(c.query == "leaked" for c in links)
