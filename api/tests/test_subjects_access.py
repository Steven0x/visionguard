"""A reviewer without access to a workspace cannot read or import its subjects."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]
_CSV = {"file": ("s.csv", b"legal_name\nJane Doe\n", "text/csv")}


def test_reviewer_without_access_cannot_list_subjects(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    # reviewer_a has access to workspace A only.
    res = client.get(
        f"/workspaces/{db.workspace_b.id}/subjects",
        headers=auth_header(db.reviewer_a_user_id),
    )
    assert res.status_code == 403


def test_reviewer_without_access_cannot_preview_import(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.post(
        f"/workspaces/{db.workspace_b.id}/subjects/import/preview",
        headers=auth_header(db.reviewer_a_user_id),
        files=_CSV,
    )
    assert res.status_code == 403


def test_reviewer_without_access_cannot_commit_import(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.post(
        f"/workspaces/{db.workspace_b.id}/subjects/import/commit",
        headers=auth_header(db.reviewer_a_user_id),
        files=_CSV,
    )
    assert res.status_code == 403
