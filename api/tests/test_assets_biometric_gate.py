"""Biometric gate on CLIP embeddings (CLAUDE.md #1): no embedding without biometric consent.

Until counsel rules on whether whole-image CLIP embeddings are biometric identifiers, we treat
them as biometric — computed only with active biometric consent, deleted on revocation.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from api.app.db.session import tenant_session
from api.app.models.assets import Asset
from api.app.models.rights import ConsentType
from api.app.models.subjects import Subject
from api.app.services import consent as consent_service
from api.tests.conftest import Fixtures
from api.tests.imgutil import png_bytes


def _subject(client: TestClient, auth_header, db: Fixtures, ws) -> int:
    return client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Gate Subject"},
    ).json()["id"]


def _upload(client: TestClient, auth_header, db: Fixtures, ws, sid: int) -> dict:
    return client.post(
        f"/workspaces/{ws.id}/subjects/{sid}/assets",
        headers=auth_header(db.admin_user_id),
        files={"file": ("p.png", png_bytes(), "application/octet-stream")},
    ).json()


def test_no_embedding_without_biometric_consent(
    client: TestClient, auth_header, db: Fixtures, new_workspace
) -> None:
    sid = _subject(client, auth_header, db, new_workspace)
    body = _upload(client, auth_header, db, new_workspace, sid)
    assert body["status"] == "ready"
    assert body["has_embedding"] is False  # exact-match-only — no biometric consent

    with tenant_session(new_workspace.schema_name) as s:
        asset = s.get(Asset, body["id"])
        assert asset is not None
        assert asset.embedding is None
        assert asset.phash  # pHash + sha are still computed
        assert asset.sha256


def test_granting_biometric_consent_backfills_embeddings(
    client: TestClient, auth_header, db: Fixtures, new_workspace
) -> None:
    schema = new_workspace.schema_name
    sid = _subject(client, auth_header, db, new_workspace)
    body = _upload(client, auth_header, db, new_workspace, sid)
    assert body["has_embedding"] is False

    # Unblock the subject (non-IL/WA) so biometric consent is permitted, then grant it.
    with tenant_session(schema) as s:
        subject = s.get(Subject, sid)
        assert subject is not None
        subject.biometrics_blocked = False

    with tenant_session(schema) as s:
        consent_service.create_consent_record(
            s, workspace_id=new_workspace.id, schema=schema, actor_staff_id=db.admin_staff_id,
            subject_id=sid, type=ConsentType.biometric, data=b"%PDF-1.4",
            content_type="application/pdf", file_name="c.pdf", signer_name="x",
            signed_date=date(2026, 1, 1),
        )

    # Granting consent queued embed_asset (eager) → the asset now carries an embedding.
    with tenant_session(schema) as s:
        asset = s.get(Asset, body["id"])
        assert asset is not None
        assert asset.embedding is not None
        assert len(list(asset.embedding)) == 512

    listed = client.get(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/assets",
        headers=auth_header(db.admin_user_id),
    ).json()
    assert listed[0]["has_embedding"] is True
