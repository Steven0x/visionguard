"""Guards (Slices 5–6): an OPEN (non-terminal) case blocks asset deletion and candidate/
thumbnail cleanup; a terminal case releases them."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api.app.db.session import tenant_session
from api.app.models.assets import Asset
from api.app.models.cases import CaseStatus
from api.app.models.discovery import DiscoveryCandidate
from api.app.models.public import Workspace
from api.app.services.assets import can_delete_asset

from .casehelpers import make_case
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


def test_open_filed_case_pins_asset_but_terminal_releases_it(
    new_workspace: Workspace,
) -> None:
    """The Slice-6 broadening: an OPEN case (e.g. filed) still pins its asset; a terminal
    (closed) case no longer does."""
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    filed_asset = add_asset(schema, subject_id, phash="ffffffffffffffff")
    closed_asset = add_asset(schema, subject_id, phash="eeeeeeeeeeeeeeee")
    make_case(schema, subject_id, status=CaseStatus.filed, matched_asset_id=filed_asset)
    make_case(schema, subject_id, status=CaseStatus.closed, matched_asset_id=closed_asset)

    with tenant_session(schema) as session:
        pinned = session.get(Asset, filed_asset)
        released = session.get(Asset, closed_asset)
        assert pinned is not None and released is not None
        assert can_delete_asset(session, pinned) is False  # filed = open → pinned
        assert can_delete_asset(session, released) is True  # closed = terminal → free


def test_cleanup_retains_candidate_referenced_by_open_case(
    db, new_workspace: Workspace
) -> None:
    from worker.discovery import cleanup_expired_thumbnails

    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    kept = add_candidate(schema, subject_id, source_url="https://k.example/1.jpg")
    kept_filed = add_candidate(schema, subject_id, source_url="https://f.example/3.jpg")
    purged = add_candidate(schema, subject_id, source_url="https://p.example/2.jpg")
    add_confirmed_case(schema, subject_id, candidate_id=kept, matched_asset_id=None)
    # A filed (open, non-confirmed) case must also pin its candidate.
    make_case(schema, subject_id, status=CaseStatus.filed, candidate_id=kept_filed)

    # Age all candidates well past the retention window.
    old = datetime.now(UTC) - timedelta(days=9999)
    with tenant_session(schema) as session:
        for cid in (kept, kept_filed, purged):
            candidate = session.get(DiscoveryCandidate, cid)
            assert candidate is not None
            candidate.discovered_at = old

    cleanup_expired_thumbnails()

    with tenant_session(schema) as session:
        assert session.get(DiscoveryCandidate, kept) is not None  # confirmed case → retained
        assert session.get(DiscoveryCandidate, kept_filed) is not None  # filed case → retained
        assert session.get(DiscoveryCandidate, purged) is None  # unreferenced → purged
