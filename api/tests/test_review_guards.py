"""Slice 5 guards: a confirmed case blocks asset deletion and candidate/thumbnail cleanup."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api.app.db.session import tenant_session
from api.app.models.assets import Asset
from api.app.models.discovery import DiscoveryCandidate
from api.app.models.public import Workspace
from api.app.services.assets import can_delete_asset

from .reviewhelpers import add_asset, add_candidate, add_confirmed_case, make_subject

Auth = Callable[..., dict[str, str]]


def test_confirmed_case_blocks_asset_delete(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    asset_id = add_asset(schema, subject_id, phash="ffffffffffffffff")
    cid = add_candidate(schema, subject_id, best_match_asset_id=asset_id)
    add_confirmed_case(schema, subject_id, candidate_id=cid, matched_asset_id=asset_id)

    with tenant_session(schema) as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert can_delete_asset(session, asset) is False

    r = client.delete(
        f"/workspaces/{new_workspace.id}/subjects/{subject_id}/assets/{asset_id}",
        headers=auth_header("admin_user"),
    )
    assert r.status_code == 409


def test_cleanup_retains_candidate_referenced_by_confirmed_case(
    db, new_workspace: Workspace
) -> None:
    from worker.discovery import cleanup_expired_thumbnails

    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    kept = add_candidate(schema, subject_id, source_url="https://k.example/1.jpg")
    purged = add_candidate(schema, subject_id, source_url="https://p.example/2.jpg")
    add_confirmed_case(schema, subject_id, candidate_id=kept, matched_asset_id=None)

    # Age both candidates well past the retention window.
    old = datetime.now(UTC) - timedelta(days=9999)
    with tenant_session(schema) as session:
        for cid in (kept, purged):
            candidate = session.get(DiscoveryCandidate, cid)
            assert candidate is not None
            candidate.discovered_at = old

    cleanup_expired_thumbnails()

    with tenant_session(schema) as session:
        assert session.get(DiscoveryCandidate, kept) is not None  # evidence retained
        assert session.get(DiscoveryCandidate, purged) is None  # normal purge
