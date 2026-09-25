"""Slice 5 bulk-dismiss: dry-run preview, apply, per-call cap, allowlisted forbidden."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryCandidate, ReviewStatus
from api.app.models.public import Workspace

from .reviewhelpers import add_candidate, make_subject

Auth = Callable[..., dict[str, str]]


def _pending(schema: str) -> int:
    with tenant_session(schema) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(DiscoveryCandidate)
                .where(DiscoveryCandidate.review_status == ReviewStatus.pending)
            )
            or 0
        )


def _seed(schema: str) -> int:
    subject_id = make_subject(schema)
    for i in range(3):
        add_candidate(schema, subject_id, source_url=f"https://bad.example/{i}.jpg")
    add_candidate(schema, subject_id, source_url="https://good.example/keep.jpg")
    return subject_id


def test_bulk_dry_run_previews_then_applies(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    _seed(schema)
    url = f"/workspaces/{new_workspace.id}/review/bulk-dismiss"

    body = {"domain": "bad.example", "reason": "not_a_match"}
    preview = client.post(url, headers=hdr, json={**body, "dry_run": True})
    assert preview.status_code == 200
    assert preview.json() == {"count": 3, "applied": False}
    assert _pending(schema) == 4  # dry run changed nothing

    applied = client.post(url, headers=hdr, json={**body, "dry_run": False})
    assert applied.status_code == 200
    assert applied.json() == {"count": 3, "applied": True}
    with tenant_session(schema) as session:
        remaining = list(
            session.scalars(
                select(DiscoveryCandidate).where(
                    DiscoveryCandidate.review_status == ReviewStatus.pending
                )
            ).all()
        )
    assert [c.source_url for c in remaining] == ["https://good.example/keep.jpg"]


def test_bulk_rejects_allowlisted_reason(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    _seed(new_workspace.schema_name)
    r = client.post(
        f"/workspaces/{new_workspace.id}/review/bulk-dismiss",
        headers=auth_header("admin_user"),
        json={"domain": "bad.example", "reason": "allowlisted", "dry_run": False},
    )
    assert r.status_code == 422


def test_bulk_cap_enforced(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    schema = new_workspace.schema_name
    _seed(schema)
    settings = get_settings()
    original = settings.review_bulk_dismiss_max
    settings.review_bulk_dismiss_max = 1  # 3 matches > cap
    try:
        r = client.post(
            f"/workspaces/{new_workspace.id}/review/bulk-dismiss",
            headers=auth_header("admin_user"),
            json={"domain": "bad.example", "reason": "not_a_match", "dry_run": False},
        )
        assert r.status_code == 422
    finally:
        settings.review_bulk_dismiss_max = original
