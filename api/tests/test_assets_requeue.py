"""CLI/service backfills: requeue stuck-pending assets, and reprocess ready assets."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.db.session import tenant_session
from api.app.models.assets import Asset, AssetStatus
from api.app.models.public import Workspace
from api.app.services import assets as asset_service
from api.tests.conftest import Fixtures
from api.tests.imgutil import png_bytes


def _subject(client: TestClient, auth_header, db: Fixtures, ws: Workspace) -> int:
    return client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Requeue Subject"},
    ).json()["id"]


def _upload_ready(client: TestClient, auth_header, db: Fixtures, ws: Workspace, sid: int) -> int:
    body = client.post(
        f"/workspaces/{ws.id}/subjects/{sid}/assets",
        headers=auth_header(db.admin_user_id),
        files={"file": ("p.png", png_bytes(), "application/octet-stream")},
    ).json()
    assert body["status"] == "ready"
    return body["id"]


def test_requeue_pending_assets_reprocesses_stuck_assets(
    client: TestClient, auth_header, db: Fixtures, new_workspace
) -> None:
    sid = _subject(client, auth_header, db, new_workspace)
    asset_id = _upload_ready(client, auth_header, db, new_workspace, sid)
    # Simulate an asset left 'pending' by a worker that never consumed it (the spawn bug).
    with tenant_session(new_workspace.schema_name) as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        asset.status = AssetStatus.pending
        asset.phash = None

    with tenant_session(new_workspace.schema_name) as s:
        count = asset_service.requeue_pending_assets(s, workspace_id=new_workspace.id)
    assert count == 1  # eager mode ran fingerprint_asset inline

    with tenant_session(new_workspace.schema_name) as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        assert asset.status == AssetStatus.ready
        assert asset.phash

    # Nothing left pending → a second run requeues zero.
    with tenant_session(new_workspace.schema_name) as s:
        assert asset_service.requeue_pending_assets(s, workspace_id=new_workspace.id) == 0


def test_reprocess_assets_rederives_ready_assets(
    client: TestClient, auth_header, db: Fixtures, new_workspace
) -> None:
    sid = _subject(client, auth_header, db, new_workspace)
    asset_id = _upload_ready(client, auth_header, db, new_workspace, sid)

    with tenant_session(new_workspace.schema_name) as s:
        count = asset_service.reprocess_assets(s, workspace_id=new_workspace.id)
    assert count == 1

    with tenant_session(new_workspace.schema_name) as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        assert asset.status == AssetStatus.ready
        assert asset.phash and asset.embedding is not None

    # Scoping to an unrelated subject enqueues nothing.
    with tenant_session(new_workspace.schema_name) as s:
        assert (
            asset_service.reprocess_assets(s, workspace_id=new_workspace.id, subject_id=sid + 999)
            == 0
        )
