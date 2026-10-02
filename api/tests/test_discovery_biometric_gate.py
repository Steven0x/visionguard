"""Discovery candidates (found images) respect the biometric gate — red-team Finding 1.

A reverse-image hit is subject-associated imagery; its CLIP embedding is treated as biometric
(CLAUDE.md #1) and must not be computed/stored without active biometric consent.
"""

from __future__ import annotations

from datetime import date

from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryCandidate, DiscoveryRun, RunKind
from api.app.models.rights import ConsentRecord, ConsentType, RecordStatus
from api.app.models.subjects import Subject
from api.app.net.fetcher import FakeFetcher
from api.app.services import discovery as svc
from api.tests.discohelpers import authorized_subject


def _run(schema: str, subject_id: int) -> int:
    with tenant_session(schema) as s:
        run = DiscoveryRun(kind=RunKind.reverse_image, subject_id=subject_id)
        s.add(run)
        s.flush()
        return run.id


def _add_candidate(schema: str, ws_id: int, sid: int, run_id: int, url: str) -> DiscoveryCandidate:
    with tenant_session(schema) as s:
        cand = svc.add_image_candidate(
            s, workspace_id=ws_id, schema=schema, subject_id=sid, run_id=run_id,
            provider="x", query=None, source_url=url, page_url=None, fetcher=FakeFetcher(),
        )
        assert cand is not None
        s.expunge(cand)
        return cand


def _grant_biometrics(schema: str, sid: int) -> None:
    with tenant_session(schema) as s:
        subject = s.get(Subject, sid)
        assert subject is not None
        subject.biometrics_blocked = False
        s.add(
            ConsentRecord(
                subject_id=sid, type=ConsentType.biometric, file_key="k", file_name="c.pdf",
                content_type="application/pdf", signer_name="x",
                signed_date=date(2026, 1, 1), status=RecordStatus.active,
            )
        )


def test_found_image_not_embedded_without_biometric_consent(db, new_workspace) -> None:
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema)  # enforcement auth only; no biometric consent, blocked
    run_id = _run(schema, sid)
    cand = _add_candidate(schema, new_workspace.id, sid, run_id, "https://found.example/a.png")
    assert cand.embedding is None  # gated — no biometric consent
    assert cand.phash  # pHash still stored → pHash + rules matching still works


def test_found_image_embedded_with_biometric_consent(db, new_workspace) -> None:
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema)
    _grant_biometrics(schema, sid)
    run_id = _run(schema, sid)
    cand = _add_candidate(schema, new_workspace.id, sid, run_id, "https://found.example/b.png")
    assert cand.embedding is not None
