"""CSV subject import: preview, all-or-nothing commit, limits, encoding, duplicates."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.constants import SUBJECT_IMPORT_MAX_BYTES
from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.public import Workspace
from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]


def _import(client, auth_header, db, ws, path, data: bytes):
    return client.post(
        f"/workspaces/{ws.id}/subjects/import/{path}",
        headers=auth_header(db.admin_user_id),
        files={"file": ("s.csv", data, "text/csv")},
    )


def _subjects(client, auth_header, db, ws, status="active"):
    return client.get(
        f"/workspaces/{ws.id}/subjects?status={status}",
        headers=auth_header(db.admin_user_id),
    ).json()


def test_preview_reports_per_row_errors(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = b"legal_name,handles\n,@x\nValid Person,@y\n"
    res = _import(client, auth_header, db, new_workspace, "preview", data)
    assert res.status_code == 200
    body = res.json()
    assert body["has_errors"] is True
    assert body["rows"][0]["errors"]  # first row missing legal_name
    assert not body["rows"][1]["errors"]


def test_commit_is_all_or_nothing(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = b"legal_name,handles\n,@x\nValid Person,@y\n"
    res = _import(client, auth_header, db, new_workspace, "commit", data)
    assert res.status_code == 422
    assert _subjects(client, auth_header, db, new_workspace) == []  # nothing inserted


def test_commit_clean_inserts_all_and_writes_audit(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = (
        b"legal_name,stage_names,handles,residence_state,notes\n"
        b"Jane Doe,Janey;JD,@jane;ig:jane,CA,vip\n"
        b"John Roe,,tw:john,NY,\n"
    )
    res = _import(client, auth_header, db, new_workspace, "commit", data)
    assert res.status_code == 200
    assert res.json()["imported"] == 2
    assert len(_subjects(client, auth_header, db, new_workspace)) == 2

    with tenant_session(new_workspace.schema_name) as s:
        actions = set(s.scalars(select(AuditLog.action)).all())
    assert "subjects.imported" in actions


def test_rejects_file_over_byte_limit(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = b"legal_name\n" + b"a" * (SUBJECT_IMPORT_MAX_BYTES + 1)
    res = _import(client, auth_header, db, new_workspace, "commit", data)
    assert res.status_code == 422


def test_rejects_too_many_rows(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    lines = ["legal_name"] + [f"Person {i}" for i in range(1001)]
    data = "\n".join(lines).encode()
    res = _import(client, auth_header, db, new_workspace, "preview", data)
    assert res.status_code == 422


def test_handles_utf8_bom(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = "﻿".encode() + b"legal_name,handles\nBom Person,@bom\n"
    res = _import(client, auth_header, db, new_workspace, "commit", data)
    assert res.status_code == 200
    names = {s["legal_name"] for s in _subjects(client, auth_header, db, new_workspace)}
    assert "Bom Person" in names


def test_rejects_non_text_file(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = b"\xff\xfe\x00\x01 binary \x00 blob"
    res = _import(client, auth_header, db, new_workspace, "preview", data)
    assert res.status_code == 422


def test_flags_duplicate_rows_within_file(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = b"legal_name,handles\nJane Doe,@jane\nJane Doe,ig:jane;@jane\n"
    res = _import(client, auth_header, db, new_workspace, "preview", data)
    body = res.json()
    assert body["has_errors"] is True
    assert body["rows"][0]["errors"] and body["rows"][1]["errors"]
    # Commit is blocked.
    assert _import(client, auth_header, db, new_workspace, "commit", data).status_code == 422


def test_flags_duplicate_of_existing_active_subject(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    client.post(
        f"/workspaces/{new_workspace.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Jane Doe", "handles": ["@jane"]},
    )
    data = b"legal_name,handles\nJane Doe,@jane\n"
    res = _import(client, auth_header, db, new_workspace, "preview", data)
    assert res.json()["rows"][0]["errors"]


def test_name_only_match_is_not_a_duplicate(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    data = b"legal_name,handles\nSam,@sam1\nSam,@sam2\n"
    res = _import(client, auth_header, db, new_workspace, "commit", data)
    assert res.status_code == 200
    assert res.json()["imported"] == 2


def test_archived_subject_is_not_a_duplicate(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    created = client.post(
        f"/workspaces/{new_workspace.id}/subjects",
        headers=auth_header(db.admin_user_id),
        json={"legal_name": "Ann", "handles": ["@ann"]},
    ).json()
    client.post(
        f"/workspaces/{new_workspace.id}/subjects/{created['id']}/archive",
        headers=auth_header(db.admin_user_id),
    )
    data = b"legal_name,handles\nAnn,@ann\n"
    res = _import(client, auth_header, db, new_workspace, "commit", data)
    assert res.status_code == 200
    assert res.json()["imported"] == 1
