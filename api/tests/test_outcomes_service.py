"""Outcomes service (Slice 9): outcome→state mapping, effective_at defaulting, append-only
supersede, and follow-up timer resets."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.notices import Notice, NoticeStatus
from api.app.models.outcomes import OutcomeKind, RecheckResult, UrlRecheck
from api.app.services import outcomes as svc
from api.tests.casehelpers import load, make_case
from api.tests.conftest import Fixtures
from api.tests.reviewhelpers import make_subject


def _filed_case_with_notice(
    schema: str, *, claim: str = "copyright", platform: str = "generic_host"
) -> tuple[int, int]:
    subject = make_subject(schema, authorized=True)
    case_id = make_case(
        schema, subject, status=CaseStatus.filed, claim_type=claim,
        source_url="https://leak.example/p", page_url="https://leak.example/p",
    )
    with tenant_session(schema) as s:
        notice = Notice(
            case_id=case_id, channel_id=1, template_id=1, template_version=1, claim_type=claim,
            method="email", platform=platform, destination="a@b.invalid",
            status=NoticeStatus.sent, sent_at=datetime.now(UTC),
        )
        s.add(notice)
        s.flush()
        return case_id, notice.id


def _record(schema: str, wid: int, case_id: int, notice_id: int, outcome: OutcomeKind,
            **kw) -> None:
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        notice = load(s, Notice, notice_id)
        svc.record_outcome(
            s, workspace_id=wid, actor_staff_id=1, case=case, notice=notice, outcome=outcome, **kw
        )


def test_removed_moves_case_to_removed(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, notice_id = _filed_case_with_notice(schema)
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.removed)
    with tenant_session(schema) as s:
        assert load(s, Case, case_id).status == CaseStatus.removed
        assert [o.outcome for o in svc.list_outcomes(s, case_id)] == [OutcomeKind.removed]


def test_countered_moves_case_to_countered(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, notice_id = _filed_case_with_notice(schema)
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.countered)
    with tenant_session(schema) as s:
        assert load(s, Case, case_id).status == CaseStatus.countered


def test_rejected_stays_filed_and_sets_follow_up(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, notice_id = _filed_case_with_notice(schema, platform="generic_host")
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.rejected)
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert case.status == CaseStatus.filed
        # generic_host seeds a 10-day response window → due ~10 days out.
        assert case.due_at is not None
        assert case.due_at > datetime.now(UTC) + timedelta(days=8)


def test_no_response_stays_filed(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, notice_id = _filed_case_with_notice(schema)
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.no_response)
    with tenant_session(schema) as s:
        assert load(s, Case, case_id).status == CaseStatus.filed


def test_effective_at_defaults_to_earliest_gone_recheck(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, notice_id = _filed_case_with_notice(schema)
    now = datetime.now(UTC)
    with tenant_session(schema) as s:
        # A gone streak starting two days ago (older row first).
        s.add(UrlRecheck(case_id=case_id, probed_url="https://x", result=RecheckResult.gone,
                         created_at=now - timedelta(days=2)))
        s.add(UrlRecheck(case_id=case_id, probed_url="https://x", result=RecheckResult.gone,
                         created_at=now - timedelta(days=1)))
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.removed)
    with tenant_session(schema) as s:
        outcome = svc.list_outcomes(s, case_id)[0]
        assert outcome.effective_at == (now - timedelta(days=2)).date()


def test_effective_at_explicit_wins(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, notice_id = _filed_case_with_notice(schema)
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.removed,
            effective_at=date(2026, 3, 3))
    with tenant_session(schema) as s:
        assert svc.list_outcomes(s, case_id)[0].effective_at == date(2026, 3, 3)


def test_supersede_appends_and_effective_is_latest(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, notice_id = _filed_case_with_notice(schema)
    # First a no_response (case stays filed), then correct it to removed.
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.no_response)
    with tenant_session(schema) as s:
        first = svc.list_outcomes(s, case_id)[0]
        first_id = first.id
    _record(schema, new_workspace.id, case_id, notice_id, OutcomeKind.removed,
            supersedes_id=first_id, note="platform actually took it down")
    with tenant_session(schema) as s:
        rows = svc.list_outcomes(s, case_id)
        assert len(rows) == 2  # append-only: both survive
        eff = svc.effective_outcome(s, notice_id)
        assert eff is not None and eff.outcome == OutcomeKind.removed
        assert eff.supersedes_id == first_id


def test_dismiss_removal_proposal_clears_flag(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    case_id, _ = _filed_case_with_notice(schema)
    with tenant_session(schema) as s:
        load(s, Case, case_id).removal_proposed_at = datetime.now(UTC)
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        svc.dismiss_removal_proposal(
            s, workspace_id=new_workspace.id, actor_staff_id=1, case=case, note="still up"
        )
        assert case.removal_proposed_at is None
