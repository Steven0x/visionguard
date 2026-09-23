"""Archiving is a status change, never a hard delete."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.app.models.public import Workspace
from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]


def test_archive_hides_from_default_list_but_keeps_the_row(
    client: TestClient, auth_header: Header, db: Fixtures, new_workspace: Workspace
) -> None:
    base = f"/workspaces/{new_workspace.id}/subjects"
    hdr = auth_header(db.admin_user_id)

    keep = client.post(base, headers=hdr, json={"legal_name": "Keep Me"}).json()
    gone = client.post(base, headers=hdr, json={"legal_name": "Archive Me"}).json()

    res = client.post(f"{base}/{gone['id']}/archive", headers=hdr)
    assert res.status_code == 200
    assert res.json()["status"] == "archived"

    active = {s["legal_name"] for s in client.get(base, headers=hdr).json()}
    assert "Keep Me" in active
    assert "Archive Me" not in active

    every = {s["legal_name"] for s in client.get(f"{base}?status=all", headers=hdr).json()}
    assert {"Keep Me", "Archive Me"} <= every

    # The archived row is still retrievable (not deleted).
    assert client.get(f"{base}/{gone['id']}", headers=hdr).status_code == 200
    _ = keep
