"""Workspace-access enforcement on workspace-scoped routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]


def test_admin_reaches_any_workspace(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    for ws in (db.workspace_a, db.workspace_b):
        res = client.get(f"/workspaces/{ws.id}/me", headers=auth_header(db.admin_user_id))
        assert res.status_code == 200, res.text
        assert res.json()["workspace_id"] == ws.id


def test_reviewer_reaches_only_granted_workspace(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    ok = client.get(
        f"/workspaces/{db.workspace_a.id}/me",
        headers=auth_header(db.reviewer_a_user_id),
    )
    assert ok.status_code == 200

    # Reviewer A has no grant for workspace B → 403, and no tenant session is opened.
    denied = client.get(
        f"/workspaces/{db.workspace_b.id}/me",
        headers=auth_header(db.reviewer_a_user_id),
    )
    assert denied.status_code == 403


def test_reviewer_without_any_grant_is_denied(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.get(
        f"/workspaces/{db.workspace_a.id}/me",
        headers=auth_header(db.reviewer_none_user_id),
    )
    assert res.status_code == 403


def test_unknown_workspace_is_404_for_admin(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.get("/workspaces/999999/me", headers=auth_header(db.admin_user_id))
    assert res.status_code == 404
