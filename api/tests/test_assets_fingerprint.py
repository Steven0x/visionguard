"""Fingerprinting: ready state, duplicate detection, failure/retry/cap, atomic claim."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from worker.tasks import fingerprint_asset

import api.app.fingerprint.embedder as embedder_mod
from api.app.db.session import tenant_session
from api.app.models.assets import Asset, AssetStatus
from api.app.models.public import Workspace
from api.app.models.rights import ConsentRecord, ConsentType, RecordStatus
from api.app.models.subjects import Subject
from api.tests.conftest import Fixtures
from api.tests.imgutil import png_bytes


def _subject(client, auth_header, db, ws: Workspace) -> int:
    return client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Fp Subject"},
    ).json()["id"]


def _enable_biometrics(schema: str, subject_id: int) -> None:
    """Grant biometric consent + unblock the subject, so the (gated) CLIP embedding is computed."""
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


def _upload(client, auth_header, db, ws, sid, content: bytes):
    return client.post(
        f"/workspaces/{ws.id}/subjects/{sid}/assets",
        headers=auth_header(db.admin_user_id),
        files={"file": ("p.png", content, "application/octet-stream")},
    )


def test_upload_becomes_ready_with_fingerprints(
    client: TestClient, auth_header, db: Fixtures, new_workspace
):
    sid = _subject(client, auth_header, db, new_workspace)
    _enable_biometrics(new_workspace.schema_name, sid)  # embedding is biometric-gated
    body = _upload(client, auth_header, db, new_workspace, sid, png_bytes()).json()
    assert body["status"] == "ready"
    assert body["sha256"] and body["phash"]
    assert body["has_embedding"] is True

    with tenant_session(new_workspace.schema_name) as s:
        asset = s.get(Asset, body["id"])
        assert asset is not None
        assert asset.embedding is not None
        assert len(list(asset.embedding)) == 512


def test_exact_duplicate_is_flagged(client: TestClient, auth_header, db: Fixtures, new_workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    same = png_bytes(color=(7, 7, 7))
    first = _upload(client, auth_header, db, new_workspace, sid, same).json()
    second = _upload(client, auth_header, db, new_workspace, sid, same).json()
    assert second["duplicate_of_asset_id"] == first["id"]


def test_failure_then_retry_recovers(
    client: TestClient, auth_header, db: Fixtures, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    class _Boom:
        def embed(self, data: bytes) -> list[float]:
            raise RuntimeError("boom")

    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: _Boom())
    sid = _subject(client, auth_header, db, new_workspace)
    _enable_biometrics(new_workspace.schema_name, sid)  # so the (gated) embedder is invoked
    failed = _upload(client, auth_header, db, new_workspace, sid, png_bytes()).json()
    assert failed["status"] == "failed"
    assert failed["attempts"] == 1
    assert failed["error"]

    # Heal the embedder and retry → ready.
    monkeypatch.undo()
    res = client.post(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/assets/{failed['id']}/retry",
        headers=auth_header(db.admin_user_id),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ready"


def test_retry_refused_past_attempt_cap(
    client: TestClient, auth_header, db: Fixtures, new_workspace
):
    sid = _subject(client, auth_header, db, new_workspace)
    asset_id = _upload(client, auth_header, db, new_workspace, sid, png_bytes()).json()["id"]
    with tenant_session(new_workspace.schema_name) as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        asset.status = AssetStatus.failed
        asset.attempts = 5
    res = client.post(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/assets/{asset_id}/retry",
        headers=auth_header(db.admin_user_id),
    )
    assert res.status_code == 409


def test_retry_increments_attempts_until_cap(
    client: TestClient, auth_header, db: Fixtures, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    class _Boom:
        def embed(self, data: bytes) -> list[float]:
            raise RuntimeError("boom")

    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: _Boom())
    sid = _subject(client, auth_header, db, new_workspace)
    _enable_biometrics(new_workspace.schema_name, sid)  # so the (gated) embedder is invoked
    body = _upload(client, auth_header, db, new_workspace, sid, png_bytes()).json()
    assert body["attempts"] == 1
    retry = f"/workspaces/{new_workspace.id}/subjects/{sid}/assets/{body['id']}/retry"

    for expected in (2, 3, 4, 5):
        res = client.post(retry, headers=auth_header(db.admin_user_id))
        assert res.status_code == 200
        assert res.json()["attempts"] == expected
        assert res.json()["status"] == "failed"

    # attempts == 5 → capped; no further retry.
    assert client.post(retry, headers=auth_header(db.admin_user_id)).status_code == 409


def test_atomic_claim_is_a_noop_for_non_pending(db: Fixtures, new_workspace):
    # An already-ready asset can't be re-claimed by a second worker.
    with tenant_session(new_workspace.schema_name) as s:
        from api.app.models.subjects import Subject

        subject = Subject(legal_name="s")
        s.add(subject)
        s.flush()
        asset = Asset(
            subject_id=subject.id,
            file_key="k",
            thumbnail_key="t",
            file_name="a.png",
            content_type="image/png",
            size_bytes=1,
            status=AssetStatus.ready,
        )
        s.add(asset)
        s.flush()
        asset_id = asset.id

    assert fingerprint_asset.run(new_workspace.id, asset_id) == "skipped"
