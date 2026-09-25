"""Asset upload validation: sniffing, size cap, decompression bombs, corrupt images."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.app.images as images_mod
from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.assets import Asset
from api.app.models.public import Workspace
from api.tests.conftest import Fixtures
from api.tests.imgutil import jpeg_bytes, png_bytes, webp_bytes


def _subject(client, auth_header, db, ws: Workspace) -> int:
    return client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Asset Subject"},
    ).json()["id"]


def _upload(client, auth_header, db, ws, sid, content: bytes, name="p.img"):
    return client.post(
        f"/workspaces/{ws.id}/subjects/{sid}/assets",
        headers=auth_header(db.admin_user_id),
        files={"file": (name, content, "application/octet-stream")},
    )


def test_accepts_jpeg_png_webp(client: TestClient, auth_header, db: Fixtures, new_workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    for content, ctype in (
        (png_bytes(), "image/png"),
        (jpeg_bytes(), "image/jpeg"),
        (webp_bytes(), "image/webp"),
    ):
        res = _upload(client, auth_header, db, new_workspace, sid, content)
        assert res.status_code == 201, res.text
        assert res.json()["content_type"] == ctype


def test_thumbnail_object_is_created_as_jpeg(
    client: TestClient, auth_header, db: Fixtures, new_workspace
):
    from api.app.storage import get_storage

    sid = _subject(client, auth_header, db, new_workspace)
    asset_id = _upload(client, auth_header, db, new_workspace, sid, png_bytes()).json()["id"]
    with tenant_session(new_workspace.schema_name) as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        thumb_key = asset.thumbnail_key
    thumb = get_storage().get_object(thumb_key)
    assert thumb.startswith(b"\xff\xd8\xff")  # JPEG


def test_rejects_non_image(client: TestClient, auth_header, db: Fixtures, new_workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    res = _upload(client, auth_header, db, new_workspace, sid, b"%PDF-1.4 not an image")
    assert res.status_code == 422


def test_rejects_oversized(
    client: TestClient, auth_header, db: Fixtures, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(get_settings(), "asset_max_upload_bytes", 64)
    sid = _subject(client, auth_header, db, new_workspace)
    res = _upload(client, auth_header, db, new_workspace, sid, png_bytes(size=(200, 200)))
    assert res.status_code == 422


def test_rejects_decompression_bomb(
    client: TestClient, auth_header, db: Fixtures, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    # Lower the pixel ceiling so a normal image trips the bomb guard (memory-light).
    monkeypatch.setattr(images_mod.Image, "MAX_IMAGE_PIXELS", 10)
    sid = _subject(client, auth_header, db, new_workspace)
    res = _upload(client, auth_header, db, new_workspace, sid, png_bytes(size=(64, 64)))
    assert res.status_code == 422


def test_rejects_corrupt_image(client: TestClient, auth_header, db: Fixtures, new_workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    corrupt = b"\x89PNG\r\n\x1a\n" + b"garbage-not-a-real-png"
    res = _upload(client, auth_header, db, new_workspace, sid, corrupt)
    assert res.status_code == 422
