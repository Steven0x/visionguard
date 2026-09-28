"""URL re-check (Slice 9): classification, the 2×/24h removal gate, and the gone→live
reappearance gate. `live` never proposes anything (soft-404s); nothing auto-transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.outcomes import RecheckResult, UrlRecheck
from api.app.net.fetcher import ProbeResult
from api.app.services import recheck as svc
from api.tests.casehelpers import load, make_case
from api.tests.conftest import Fixtures
from api.tests.reviewhelpers import make_subject


def _p(status: int | None, *, reachable: bool = True, error_kind: str | None = None) -> ProbeResult:
    return ProbeResult(final_url="https://x", http_status=status, reachable=reachable,
                       error_kind=error_kind)


def test_classify() -> None:
    assert svc.classify(_p(200)) == RecheckResult.live
    assert svc.classify(_p(204)) == RecheckResult.live
    assert svc.classify(_p(404)) == RecheckResult.gone
    assert svc.classify(_p(410)) == RecheckResult.gone
    assert svc.classify(_p(451)) == RecheckResult.gone
    # Login wall / rate limit / server error are inconclusive, never "gone".
    assert svc.classify(_p(403)) == RecheckResult.error
    assert svc.classify(_p(429)) == RecheckResult.error
    assert svc.classify(_p(503)) == RecheckResult.error
    # Connection refused = gone signal; a timeout is inconclusive.
    assert svc.classify(_p(None, reachable=False, error_kind="connect:ConnectError")) \
        == RecheckResult.gone
    assert svc.classify(_p(None, reachable=False, error_kind="timeout")) == RecheckResult.error


def _add_recheck(schema: str, case_id: int, result: RecheckResult, when: datetime) -> None:
    with tenant_session(schema) as s:
        s.add(UrlRecheck(case_id=case_id, probed_url="https://x", result=result, created_at=when))


class _StubFetcher:
    def __init__(self, result: ProbeResult) -> None:
        self._result = result

    def fetch(self, url: str):  # pragma: no cover - unused
        raise NotImplementedError

    def probe(self, url: str) -> ProbeResult:
        return ProbeResult(final_url=url, http_status=self._result.http_status,
                           reachable=self._result.reachable, error_kind=self._result.error_kind)


def test_filed_removal_proposed_on_two_gone_24h_apart(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = make_case(schema, subject, status=CaseStatus.filed, source_url="https://leak.example/p")
    now = datetime.now(UTC)
    _add_recheck(schema, case_id, RecheckResult.gone, now - timedelta(hours=25))
    _add_recheck(schema, case_id, RecheckResult.gone, now)
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert svc.evaluate_filed(s, workspace_id=new_workspace.id, case=case) is True
        assert case.removal_proposed_at is not None


def test_filed_no_proposal_when_gone_too_close(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = make_case(schema, subject, status=CaseStatus.filed, source_url="https://leak.example/p")
    now = datetime.now(UTC)
    _add_recheck(schema, case_id, RecheckResult.gone, now - timedelta(hours=3))
    _add_recheck(schema, case_id, RecheckResult.gone, now)
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert svc.evaluate_filed(s, workspace_id=new_workspace.id, case=case) is False
        assert case.removal_proposed_at is None


def test_filed_no_proposal_when_latest_is_live(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = make_case(schema, subject, status=CaseStatus.filed, source_url="https://leak.example/p")
    now = datetime.now(UTC)
    _add_recheck(schema, case_id, RecheckResult.gone, now - timedelta(hours=25))
    _add_recheck(schema, case_id, RecheckResult.live, now)  # soft-404 / came back
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert svc.evaluate_filed(s, workspace_id=new_workspace.id, case=case) is False
        assert case.removal_proposed_at is None


def test_monitoring_reappearance_only_on_gone_to_live(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = make_case(schema, subject, status=CaseStatus.monitoring,
                        source_url="https://leak.example/p")
    now = datetime.now(UTC)
    _add_recheck(schema, case_id, RecheckResult.gone, now - timedelta(hours=25))
    _add_recheck(schema, case_id, RecheckResult.live, now)
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert svc.evaluate_monitoring(s, workspace_id=new_workspace.id, case=case) is True
        assert case.reappearance_proposed_at is not None


def test_monitoring_no_reappearance_on_standing_live(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = make_case(schema, subject, status=CaseStatus.monitoring,
                        source_url="https://leak.example/p")
    now = datetime.now(UTC)
    _add_recheck(schema, case_id, RecheckResult.live, now - timedelta(hours=25))
    _add_recheck(schema, case_id, RecheckResult.live, now)
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert svc.evaluate_monitoring(s, workspace_id=new_workspace.id, case=case) is False
        assert case.reappearance_proposed_at is None


def test_dismissed_removal_not_reraised_until_fresh_streak(db: Fixtures, new_workspace) -> None:
    from api.app.services import outcomes as outcomes_svc

    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = make_case(schema, subject, status=CaseStatus.filed,
                        source_url="https://leak.example/p")
    now = datetime.now(UTC)
    _add_recheck(schema, case_id, RecheckResult.gone, now - timedelta(hours=25))
    _add_recheck(schema, case_id, RecheckResult.gone, now - timedelta(hours=1))
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert svc.evaluate_filed(s, workspace_id=new_workspace.id, case=case) is True
        # Dismiss the false positive; the same (immutable) gone rechecks must NOT re-raise it.
        outcomes_svc.dismiss_removal_proposal(
            s, workspace_id=new_workspace.id, actor_staff_id=1, case=case, note="geo-block"
        )
        assert svc.evaluate_filed(s, workspace_id=new_workspace.id, case=case) is False
        assert case.removal_proposed_at is None
    # A fresh gone streak entirely after the dismissal re-proposes.
    _add_recheck(schema, case_id, RecheckResult.gone, now + timedelta(hours=24))
    _add_recheck(schema, case_id, RecheckResult.gone, now + timedelta(hours=49))
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert svc.evaluate_filed(s, workspace_id=new_workspace.id, case=case) is True


def test_run_recheck_records_row_and_probes_page_url(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = make_case(
        schema, subject, status=CaseStatus.filed,
        source_url="https://cdn.example/img.jpg", page_url="https://host.example/post",
    )
    fetcher = _StubFetcher(_p(404))
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        row = svc.run_recheck(s, workspace_id=new_workspace.id, case=case, fetcher=fetcher)
        assert row is not None
        assert row.probed_url == "https://host.example/post"  # page_url, not the CDN source
        assert row.result == RecheckResult.gone
