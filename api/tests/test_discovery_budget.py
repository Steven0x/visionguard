"""Per-workspace monthly call budget with a hard stop at the boundary."""

from __future__ import annotations

from sqlalchemy import select
from worker.discovery import keyword_scan, reverse_image_scan

from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryRun, RunKind, RunStatus
from api.app.services.discovery import get_or_create_settings
from api.tests.discohelpers import authorized_subject


def _set_budget(schema: str, budget: int) -> None:
    with tenant_session(schema) as s:
        get_or_create_settings(s).monthly_call_budget = budget


def test_blocked_when_budget_is_zero(db, new_workspace):
    _set_budget(new_workspace.schema_name, 0)
    sid, aid = authorized_subject(new_workspace.schema_name, ready_asset=True)
    assert reverse_image_scan.run(new_workspace.id, sid, aid) == "blocked"
    with tenant_session(new_workspace.schema_name) as s:
        run = s.scalar(select(DiscoveryRun).order_by(DiscoveryRun.id.desc()))
        assert run.status == RunStatus.blocked
        assert run.calls_made == 0


def test_keyword_scan_stops_partial_at_boundary(db, new_workspace):
    _set_budget(new_workspace.schema_name, 1)
    sid, _ = authorized_subject(
        new_workspace.schema_name, keywords=("alpha", "beta", "gamma")
    )
    keyword_scan.run(new_workspace.id, sid)
    with tenant_session(new_workspace.schema_name) as s:
        run = s.scalar(
            select(DiscoveryRun)
            .where(DiscoveryRun.kind == RunKind.keyword)
            .order_by(DiscoveryRun.id.desc())
        )
        # 3 identifiers, budget 1 → one call made, run capped as partial.
        assert run.status == RunStatus.partial
        assert run.calls_made == 1
