"""The monitoring-tail beat (Slice 9): removed→monitoring once the proof capture seals, and
monitoring→closed once the watch window elapses (unless a reappearance is pending)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from worker.rechecks import run_monitoring_lifecycle

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseEvent, CaseEventKind, CaseStatus
from api.app.models.evidence import (
    CaptureKind,
    CaptureStatus,
    EvidenceCapture,
    TimestampStatus,
)
from api.app.models.outcomes import RecheckResult, UrlRecheck
from api.tests.casehelpers import load, make_case, past_due
from api.tests.conftest import Fixtures
from api.tests.reviewhelpers import make_subject


def _removed_monitoring_case(
    schema: str, subject: int, *, rechecks: list[RecheckResult]
) -> int:
    """A monitoring case (watch window elapsed) that was recorded removed 20 days ago, with the
    given rechecks recorded since — to exercise the removal-verification gate."""
    removed_at = datetime.now(UTC) - timedelta(days=20)
    case_id = make_case(
        schema, subject, status=CaseStatus.monitoring, due_at=past_due(),
        source_url="https://leak.example/p",
    )
    with tenant_session(schema) as s:
        s.add(CaseEvent(
            case_id=case_id, kind=CaseEventKind.transition, from_status="filed",
            to_status="removed", created_at=removed_at,
        ))
        for i, result in enumerate(rechecks):
            s.add(UrlRecheck(
                case_id=case_id, probed_url="https://leak.example/p", result=result,
                created_at=removed_at + timedelta(days=i + 1),
            ))
    return case_id


def _seal_proof(schema: str, case_id: int) -> None:
    with tenant_session(schema) as s:
        s.add(EvidenceCapture(
            case_id=case_id, kind=CaptureKind.proof_of_removal, status=CaptureStatus.sealed,
            capture_finished_at=datetime.now(UTC), manifest_sha256="0" * 64,
            timestamp_status=TimestampStatus.ok,
        ))


def test_removed_advances_to_monitoring_after_proof_seals(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    with_proof = make_case(schema, subject, status=CaseStatus.removed)
    without_proof = make_case(schema, subject, status=CaseStatus.removed)
    _seal_proof(schema, with_proof)

    run_monitoring_lifecycle()

    with tenant_session(schema) as s:
        advanced = load(s, Case, with_proof)
        waiting = load(s, Case, without_proof)
        assert advanced.status == CaseStatus.monitoring
        assert advanced.due_at is not None  # watch window started
        assert waiting.status == CaseStatus.removed  # no sealed proof yet → held back


def test_monitoring_closes_after_window(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    expired = make_case(schema, subject, status=CaseStatus.monitoring, due_at=past_due())
    fresh = make_case(
        schema, subject, status=CaseStatus.monitoring,
        due_at=datetime.now(UTC) + timedelta(days=10),
    )
    pending = make_case(schema, subject, status=CaseStatus.monitoring, due_at=past_due())
    with tenant_session(schema) as s:
        load(s, Case, pending).reappearance_proposed_at = datetime.now(UTC)

    run_monitoring_lifecycle()

    with tenant_session(schema) as s:
        assert load(s, Case, expired).status == CaseStatus.closed
        assert load(s, Case, fresh).status == CaseStatus.monitoring  # window not elapsed
        # A pending reappearance blocks auto-close (a human must resolve it).
        assert load(s, Case, pending).status == CaseStatus.monitoring


def test_unverified_removal_is_not_closed_and_is_flagged(db: Fixtures, new_workspace) -> None:
    # A soft-404 removal: every recheck since the removal is `live` → never auto-close; flag it.
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = _removed_monitoring_case(
        schema, subject, rechecks=[RecheckResult.live, RecheckResult.live],
    )
    run_monitoring_lifecycle()
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert case.status == CaseStatus.monitoring  # held back from close
        assert case.removal_unverified_at is not None  # surfaced for a human


def test_all_error_removal_not_closed_and_flagged(db: Fixtures, new_workspace) -> None:
    # A removal only ever probed as `error` (persistent login wall / rate limit) was never
    # verified gone → must NOT auto-close.
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = _removed_monitoring_case(
        schema, subject, rechecks=[RecheckResult.error, RecheckResult.error],
    )
    run_monitoring_lifecycle()
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert case.status == CaseStatus.monitoring
        assert case.removal_unverified_at is not None


def test_recheck_verified_removal_closes_normally(db: Fixtures, new_workspace) -> None:
    # A `gone` recheck since the removal verifies it → closes normally after the window.
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = _removed_monitoring_case(
        schema, subject, rechecks=[RecheckResult.live, RecheckResult.gone],
    )
    run_monitoring_lifecycle()
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert case.status == CaseStatus.closed
        assert case.removal_unverified_at is None


def test_later_gone_clears_flag_and_closes(db: Fixtures, new_workspace) -> None:
    # Flagged unverified on the first sweep (all live); a later `gone` clears the flag and lets the
    # next sweep close it.
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    case_id = _removed_monitoring_case(
        schema, subject, rechecks=[RecheckResult.live, RecheckResult.live],
    )
    run_monitoring_lifecycle()
    with tenant_session(schema) as s:
        assert load(s, Case, case_id).removal_unverified_at is not None
        s.add(UrlRecheck(
            case_id=case_id, probed_url="https://leak.example/p", result=RecheckResult.gone,
            created_at=datetime.now(UTC),
        ))
    run_monitoring_lifecycle()
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert case.status == CaseStatus.closed
        assert case.removal_unverified_at is None
