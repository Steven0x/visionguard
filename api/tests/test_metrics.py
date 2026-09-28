"""Removal metrics (Slice 9) against a hand-computed fixture. Counted per filing (notice): a
reopened, twice-filed case contributes two filings; a withdrawn filing is excluded from the
denominator; median time-to-removal uses effective_at − sent_at."""

from __future__ import annotations

from datetime import UTC, date, datetime

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.notices import Notice, NoticeStatus
from api.app.models.outcomes import NoticeOutcome, OutcomeKind, RecheckResult, UrlRecheck
from api.app.services import metrics as svc
from api.tests.conftest import Fixtures
from api.tests.reviewhelpers import make_subject

_SENT = datetime(2026, 1, 1, tzinfo=UTC)


def _case(schema: str, subject: int, status: CaseStatus = CaseStatus.filed) -> int:
    with tenant_session(schema) as s:
        case = Case(subject_id=subject, claim_type="copyright", status=status)
        s.add(case)
        s.flush()
        return case.id


def _notice(schema: str, case_id: int, *, platform: str, claim: str,
            status: NoticeStatus = NoticeStatus.sent,
            removed_on: date | None = None) -> None:
    with tenant_session(schema) as s:
        notice = Notice(
            case_id=case_id, channel_id=1, template_id=1, template_version=1, claim_type=claim,
            method="email", platform=platform, destination="a@b.invalid", status=status,
            sent_at=_SENT,
        )
        s.add(notice)
        s.flush()
        if removed_on is not None:
            s.add(NoticeOutcome(
                case_id=case_id, notice_id=notice.id, outcome=OutcomeKind.removed,
                effective_at=removed_on,
            ))


def test_removal_metrics_hand_computed(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)

    # A reopened, twice-filed case: two instagram/copyright filings, both removed (day 3, day 5).
    reopened = _case(schema, subject)
    _notice(schema, reopened, platform="instagram", claim="copyright", removed_on=date(2026, 1, 4))
    _notice(schema, reopened, platform="instagram", claim="copyright", removed_on=date(2026, 1, 6))
    # A pending instagram/copyright filing (no outcome yet).
    _notice(schema, _case(schema, subject), platform="instagram", claim="copyright")
    # A withdrawn instagram/copyright filing — excluded from the denominator.
    _notice(schema, _case(schema, subject, CaseStatus.withdrawn),
            platform="instagram", claim="copyright", status=NoticeStatus.withdrawn)

    # A separate platform×claim: tiktok/likeness — one removed (day 10), one pending.
    _notice(schema, _case(schema, subject), platform="tiktok", claim="likeness",
            removed_on=date(2026, 1, 11))
    _notice(schema, _case(schema, subject), platform="tiktok", claim="likeness")

    with tenant_session(schema) as s:
        metrics = {(m.platform, m.claim_type): m for m in svc.removal_metrics(s)}

    ig = metrics[("instagram", "copyright")]
    assert ig.filed == 4
    assert ig.withdrawn == 1
    assert ig.removed == 2
    assert ig.removed_verified == 0 and ig.removed_staff_only == 2  # no rechecks in this fixture
    assert ig.pending == 1  # eligible (4−1=3) − removed (2)
    assert ig.removal_rate == 2 / 3
    assert ig.median_days_to_removal == 4.0  # median of [3, 5]

    tk = metrics[("tiktok", "likeness")]
    assert tk.filed == 2
    assert tk.withdrawn == 0
    assert tk.removed == 1
    assert tk.pending == 1
    assert tk.removal_rate == 0.5
    assert tk.median_days_to_removal == 10.0


def test_removed_split_verified_vs_staff_only(db: Fixtures, new_workspace) -> None:
    # Two removed x/copyright filings: one case has a `gone` recheck (verified), one has none
    # (staff-confirmed only — the honest count for a soft-404 platform).
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    verified = _case(schema, subject)
    with tenant_session(schema) as s:
        s.add(UrlRecheck(case_id=verified, probed_url="https://x", result=RecheckResult.gone))
    _notice(schema, verified, platform="x", claim="copyright", removed_on=date(2026, 1, 3))
    _notice(schema, _case(schema, subject), platform="x", claim="copyright",
            removed_on=date(2026, 1, 3))  # no rechecks → staff-only

    with tenant_session(schema) as s:
        m = {(x.platform, x.claim_type): x for x in svc.removal_metrics(s)}[("x", "copyright")]
    assert m.removed == 2
    assert m.removed_verified == 1
    assert m.removed_staff_only == 1


def test_time_to_removal_clamped_at_zero(db: Fixtures, new_workspace) -> None:
    # A mistaken effective_at before the filing date must not yield a negative time-to-removal.
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    _notice(schema, _case(schema, subject), platform="x", claim="copyright",
            removed_on=date(2025, 12, 25))  # before _SENT (2026-01-01)
    with tenant_session(schema) as s:
        m = {(x.platform, x.claim_type): x for x in svc.removal_metrics(s)}
    assert m[("x", "copyright")].median_days_to_removal == 0.0
