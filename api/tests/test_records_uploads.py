"""Document upload validation + signed-URL download (MinIO-backed)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import select

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.public import Workspace
from api.app.models.rights import RightsRecord
from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]

_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32


def _subject(client, auth_header, db, ws: Workspace) -> int:
    res = client.post(
        f"/workspaces/{ws.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Doc Subject"},
    )
    return res.json()["id"]


def _post_rights(client, auth_header, db, ws, sid, content: bytes, filename="d.pdf"):
    return client.post(
        f"/workspaces/{ws.id}/subjects/{sid}/rights",
        headers=auth_header(db.admin_user_id),
        data={"type": "self_owned_declaration", "grants_enforcement_right": "false"},
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_accepts_pdf_png_jpeg(client, auth_header, db: Fixtures, new_workspace: Workspace):
    sid = _subject(client, auth_header, db, new_workspace)
    for content, ctype in ((_PDF, "application/pdf"), (_PNG, "image/png"), (_JPEG, "image/jpeg")):
        res = _post_rights(client, auth_header, db, new_workspace, sid, content)
        assert res.status_code == 201, res.text
        assert res.json()["content_type"] == ctype


def test_rejects_disguised_non_document(
    client, auth_header, db: Fixtures, new_workspace: Workspace
):
    sid = _subject(client, auth_header, db, new_workspace)
    res = _post_rights(client, auth_header, db, new_workspace, sid, b"not a pdf at all")
    assert res.status_code == 422


def test_rejects_oversized_file(
    client, auth_header, db: Fixtures, new_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(get_settings(), "storage_max_upload_bytes", 64)
    sid = _subject(client, auth_header, db, new_workspace)
    res = _post_rights(client, auth_header, db, new_workspace, sid, _PDF + b"x" * 200)
    assert res.status_code == 422


def test_download_returns_signed_url_and_audits(
    client, auth_header, db: Fixtures, new_workspace: Workspace
):
    sid = _subject(client, auth_header, db, new_workspace)
    rights_id = _post_rights(client, auth_header, db, new_workspace, sid, _PDF).json()["id"]

    res = client.get(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/rights/{rights_id}/file",
        headers=auth_header(db.admin_user_id),
    )
    assert res.status_code == 200
    assert res.json()["url"].startswith("http")

    # Key is tenant-scoped and unguessable; upload + download are audited.
    with tenant_session(new_workspace.schema_name) as s:
        record = s.get(RightsRecord, rights_id)
        assert record is not None
        assert record.file_key.startswith(f"{new_workspace.schema_name}/rights/")
        actions = set(s.scalars(select(AuditLog.action)).all())
    assert {"rights.created", "document.uploaded", "document.downloaded"} <= actions


def test_reviewer_without_access_cannot_download(
    client, auth_header, db: Fixtures, new_workspace: Workspace
):
    # reviewer_a has no access to the freshly created workspace.
    res = client.get(
        f"/workspaces/{new_workspace.id}/subjects/1/rights/1/file",
        headers=auth_header(db.reviewer_a_user_id),
    )
    assert res.status_code == 403
