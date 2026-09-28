"""Slice 10 metrics + report, against a hand-computed fixture.

One workspace with a **reopened (twice-filed)** case and a **withdrawn** case, plus rechecks,
case-timeline transitions, review decisions and provider-cost runs — every metric is asserted
against a value computed by hand in the comments. Also: report totals == metrics-service totals
(the report layer does no counting), reproducibility/verification, and the ncii/thumbnail/
per-subject redaction rules.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseEvent, CaseEventKind, CaseStatus
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    ReviewStatus,
    RunKind,
    RunStatus,
)
from api.app.models.notices import Notice, NoticeStatus
from api.app.models.outcomes import NoticeOutcome, OutcomeKind, RecheckResult, UrlRecheck
from api.app.models.review import DismissReason, ReviewDecision, ReviewDecisionKind
from api.app.services import metrics as metrics_svc
from api.app.services import reports as reports_svc
from api.tests.conftest import Fixtures
from api.tests.reviewhelpers import make_subject

START = date(2026, 1, 1)
END = date(2026, 1, 31)


def _dt(m: int, d: int, hh: int = 12, mm: int = 0) -> datetime:
    return datetime(2026, m, d, hh, mm, tzinfo=UTC)


def _case(schema: str, subject: int, *, status: CaseStatus, created: datetime) -> int:
    with tenant_session(schema) as s:
        case = Case(subject_id=subject, claim_type="copyright", status=status, created_at=created)
        s.add(case)
        s.flush()
        return case.id


def _notice(
    schema: str,
    case_id: int,
    *,
    platform: str,
    claim: str,
    sent_at: datetime,
    status: NoticeStatus = NoticeStatus.sent,
    outcome: OutcomeKind | None = None,
    effective_at: date | None = None,
) -> None:
    with tenant_session(schema) as s:
        notice = Notice(
            case_id=case_id, channel_id=1, template_id=1, template_version=1, claim_type=claim,
            method="email", platform=platform, destination="a@b.invalid", status=status,
            sent_at=sent_at,
        )
        s.add(notice)
        s.flush()
        if outcome is not None:
            s.add(NoticeOutcome(
                case_id=case_id, notice_id=notice.id, outcome=outcome,
                effective_at=effective_at or sent_at.date(),
            ))


def _candidate(schema: str, subject: int, *, url: str, shown: datetime) -> int:
    with tenant_session(schema) as s:
        cand = DiscoveryCandidate(
            subject_id=subject, provider="serpapi", kind=CandidateKind.link, source_url=url,
            source_key=url[-60:], review_status=ReviewStatus.dismissed, shown_at=shown,
        )
        s.add(cand)
        s.flush()
        return cand.id


def _seed(schema: str, subject: int) -> None:
    """Build the hand-computed fixture (see per-metric comments)."""
    # Cases (found = cases created in [01-01, 01-31]):
    c1 = _case(schema, subject, status=CaseStatus.filed, created=_dt(1, 5))       # in period
    c2 = _case(schema, subject, status=CaseStatus.filed, created=_dt(1, 6))       # in period
    c3 = _case(schema, subject, status=CaseStatus.removed, created=_dt(1, 7))     # in period
    c4 = _case(schema, subject, status=CaseStatus.monitoring, created=_dt(1, 8))  # in period
    c5 = _case(schema, subject, status=CaseStatus.withdrawn, created=_dt(1, 9))   # in period, term
    c6 = _case(schema, subject, status=CaseStatus.filed,
               created=datetime(2025, 12, 20, 12, tzinfo=UTC))                    # BEFORE period
    # → found = c1..c5 = 5 (c6 excluded).
    # → open_cases_by_status (non-terminal snapshot) = filed:3 (c1,c2,c6), removed:1, monitoring:1.

    # c1 has a `gone` recheck → its removals are recheck-verified.
    with tenant_session(schema) as s:
        s.add(UrlRecheck(case_id=c1, probed_url="https://ig/x", result=RecheckResult.gone))

    # Filings sent in the period (the funnel):
    _notice(schema, c1, platform="instagram", claim="copyright", sent_at=_dt(1, 10),
            outcome=OutcomeKind.removed, effective_at=date(2026, 1, 13))  # 3d, verified
    _notice(schema, c1, platform="instagram", claim="copyright", sent_at=_dt(1, 20),
            outcome=OutcomeKind.removed, effective_at=date(2026, 1, 25))  # 5d, verified (refile)
    _notice(schema, c2, platform="instagram", claim="copyright", sent_at=_dt(1, 11))  # pending
    _notice(schema, c5, platform="instagram", claim="copyright", sent_at=_dt(1, 12),
            status=NoticeStatus.withdrawn)  # withdrawn
    _notice(schema, c3, platform="tiktok", claim="likeness", sent_at=_dt(1, 15),
            outcome=OutcomeKind.countered)  # countered
    _notice(schema, c4, platform="tiktok", claim="likeness", sent_at=_dt(1, 16),
            outcome=OutcomeKind.removed, effective_at=date(2026, 1, 18))  # 2d, staff-only (no gone)
    # A filing sent BEFORE the period → excluded from the report funnel (removal_metrics counts it).
    _notice(schema, c6, platform="instagram", claim="copyright",
            sent_at=datetime(2025, 12, 15, 12, tzinfo=UTC))
    # → filed=6, withdrawn=1, removed=3 (verified 2, staff-only 1), countered=1, still_pending=1.
    # → median_days_to_removal = median([3,5,2]) = 3.0.

    # Case timeline for re-upload rate: 2 real removed transitions (c1, c4) + 1 reappearance (c1).
    with tenant_session(schema) as s:
        s.add(CaseEvent(case_id=c1, kind=CaseEventKind.transition, to_status="removed"))
        s.add(CaseEvent(case_id=c4, kind=CaseEventKind.transition, to_status="removed"))
        s.add(CaseEvent(case_id=c1, kind=CaseEventKind.transition, to_status="discovered",
                        reason="reappearance"))
    # → re_upload_rate = reopened(1) / removed(2) = 0.5.

    # Review decisions with shown candidates (review-minutes) that are also licensed dismissals.
    cand1 = _candidate(schema, subject, url="https://a.example/1", shown=_dt(1, 5, 10, 0))
    cand2 = _candidate(schema, subject, url="https://a.example/2", shown=_dt(1, 6, 10, 0))
    with tenant_session(schema) as s:
        s.add(ReviewDecision(candidate_id=cand1, subject_id=subject,
                             decision=ReviewDecisionKind.dismiss, reason=DismissReason.licensed,
                             decided_at=_dt(1, 5, 10, 5)))   # 5 min, licensed, in period
        s.add(ReviewDecision(candidate_id=cand2, subject_id=subject,
                             decision=ReviewDecisionKind.dismiss, reason=DismissReason.licensed,
                             decided_at=_dt(1, 6, 10, 15)))  # 15 min, licensed, in period
        # A licensed dismissal BEFORE the period with no shown candidate → excluded from both.
        s.add(ReviewDecision(candidate_id=None, subject_id=subject,
                             decision=ReviewDecisionKind.dismiss, reason=DismissReason.licensed,
                             decided_at=datetime(2025, 12, 30, 12, tzinfo=UTC)))
    # → licensed_use_confirmations (in period) = 2; review_minutes = median([5,15]) = 10.0.

    # Provider-cost runs (per workspace, all-time). provider=None excluded.
    with tenant_session(schema) as s:
        for provider, cents in [("serpapi", 100), ("serpapi", 50), ("tineye", 30), (None, 999)]:
            s.add(DiscoveryRun(kind=RunKind.reverse_image, subject_id=subject, provider=provider,
                               status=RunStatus.completed, estimated_cost_cents=cents))
    # → provider_cost = [serpapi:150, tineye:30], total = 180.


def test_report_metrics_hand_computed(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)  # authorized + consent, no ownership
    _seed(schema, subject)

    with tenant_session(schema) as s:
        m = metrics_svc.report_metrics(
            s, subject_id=None, start=START, end=END, as_of=datetime.now(UTC)
        )

    assert m.found == 5
    assert m.filed == 6
    assert m.withdrawn == 1
    assert m.removed == 3
    assert m.removed_verified == 2
    assert m.removed_staff_only == 1
    assert m.countered == 1
    assert m.still_pending == 1
    assert m.filed == m.removed + m.countered + m.still_pending + m.withdrawn
    assert m.median_days_to_removal == 3.0
    assert m.open_cases_by_status == {"filed": 3, "removed": 1, "monitoring": 1}

    # Needs from you: no ownership record → copyright unsupported (ownership_rights bucket); auth +
    # consent present, so no missing_authorization / enforcement_consent. 2 licensed dismissals.
    assert m.needs_from_you.missing_authorization == []
    assert m.needs_from_you.ownership_rights == [subject]
    assert m.needs_from_you.enforcement_consent == []
    assert m.needs_from_you.licensed_use_confirmations == 2

    assert m.highlights == [
        "3 removed this period",
        "fastest verified removal in 3d",
        "most-hit platform: instagram (4 filings)",
    ]


def test_metrics_summary_hand_computed(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    _seed(schema, subject)

    with tenant_session(schema) as s:
        summary = metrics_svc.metrics_summary(s)

    # All 7 filings counted (incl. the pre-period one): filed=7, withdrawn=1.
    assert summary.review_precision == pytest.approx(6 / 7)
    assert summary.wrong_filing_rate == pytest.approx(1 / 7)
    # re-upload = reopened(1) / removed-transitions(2).
    assert summary.re_upload_rate == 0.5
    # review-minutes = median([5, 15]) minutes.
    assert summary.review_minutes_per_case == 10.0
    # provider cost per workspace.
    assert [(pc.provider, pc.cost_cents) for pc in summary.provider_cost] == [
        ("serpapi", 150), ("tineye", 30),
    ]
    assert summary.provider_cost_total_cents == 180
    # removal_metrics still exposed (per platform×claim); spot-check instagram/copyright.
    ig = {(r.platform, r.claim_type): r for r in summary.removals}[("instagram", "copyright")]
    assert ig.filed == 5 and ig.withdrawn == 1 and ig.removed == 2  # incl. the pre-period filing


def test_report_totals_equal_metrics(db: Fixtures, new_workspace) -> None:
    """The report layer does no counting: the sealed JSON snapshot equals report_metrics."""
    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    _seed(schema, subject)

    with tenant_session(schema) as s:
        report = reports_svc.generate_report(
            s, schema=schema, workspace_id=new_workspace.id, subject_id=None,
            start=START, end=END, actor_staff_id=db.admin_staff_id,
        )
        snapshot = reports_svc.snapshot_dict(report)
        m = metrics_svc.report_metrics(
            s, subject_id=None, start=START, end=END, as_of=datetime.now(UTC)
        )

    for key in ("found", "filed", "withdrawn", "removed", "removed_verified",
                "removed_staff_only", "countered", "still_pending"):
        assert snapshot[key] == getattr(m, key), key
    assert snapshot["median_days_to_removal"] == m.median_days_to_removal
    assert snapshot["open_cases_by_status"] == m.open_cases_by_status
    assert snapshot["highlights"] == m.highlights
    assert snapshot["needs_from_you"]["licensed_use_confirmations"] == 2


def test_report_reproducible_and_verifiable(db: Fixtures, new_workspace) -> None:
    from api.app.models.reports import Report

    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    _seed(schema, subject)
    with tenant_session(schema) as s:
        report = reports_svc.generate_report(
            s, schema=schema, workspace_id=new_workspace.id, subject_id=None,
            start=START, end=END, actor_staff_id=db.admin_staff_id,
        )
        assert reports_svc.verify_report(report) is True
        pdf_key, json_key, json_sha = report.pdf_key, report.json_key, report.json_sha256

    # Regenerating the same period/inputs yields an identical JSON snapshot (reproducible).
    with tenant_session(schema) as s:
        report2 = reports_svc.generate_report(
            s, schema=schema, workspace_id=new_workspace.id, subject_id=None,
            start=START, end=END, actor_staff_id=db.admin_staff_id,
        )
        first = reports_svc.snapshot_dict(report)
        second = reports_svc.snapshot_dict(report2)
    # `as_of` is a fresh timestamp each run; every counted number is identical.
    assert {k: v for k, v in first.items() if k != "as_of"} == {
        k: v for k, v in second.items() if k != "as_of"
    }

    # A record whose stored bytes no longer match its recorded hash fails verification. We can't
    # mutate the sealed object or the append-only row, so check a detached copy with a bad hash.
    bad = Report(
        subject_id=None, period_start=START, period_end=END, as_of=datetime.now(UTC),
        include_thumbnails=False, pdf_key=pdf_key, pdf_sha256="0" * 64,
        json_key=json_key, json_sha256=json_sha,
    )
    assert reports_svc.verify_report(bad) is False


# ── Data-minimization / redaction ─────────────────────────────────────────────


def _case_with_thumb(
    schema: str, subject: int, *, claim: str, page_url: str, sensitive: bool = True
) -> int:
    """An open case pointing at a candidate that has a (fake) stored thumbnail. Cases default to
    sensitive=True (like production); pass sensitive=False to model a reviewer-cleared case."""
    from api.app.storage import get_storage

    with tenant_session(schema) as s:
        cand = DiscoveryCandidate(
            subject_id=subject, provider="serpapi", kind=CandidateKind.image,
            source_url=page_url, source_key=page_url[-60:],
            review_status=ReviewStatus.confirmed, thumbnail_key=f"thumb/{page_url[-20:]}",
        )
        s.add(cand)
        s.flush()
        get_storage().put_object(cand.thumbnail_key, b"\x89PNGfakebytes", "image/jpeg")
        case = Case(subject_id=subject, claim_type=claim, status=CaseStatus.confirmed,
                    candidate_id=cand.id, page_url=page_url, sensitive=sensitive)
        s.add(case)
        s.flush()
        return case.id


def test_ncii_redaction_domain_only_and_no_image(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    _case_with_thumb(schema, subject, claim="ncii",
                     page_url="https://bad.example/path/to/leak?x=1")

    with tenant_session(schema) as s:
        # Even with thumbnails ON, an ncii case never yields an image and shows domain only.
        rows = reports_svc.gather_case_rows(s, subject_id=None, include_thumbnails=True)
    assert len(rows) == 1
    assert rows[0].url == "bad.example"  # no path, no query
    assert rows[0].thumbnail is None


def test_sensitive_case_never_renders_thumbnail_even_when_toggled(
    db: Fixtures, new_workspace
) -> None:
    """Leaked paid content is often filed as COPYRIGHT — a sensitive copyright case with the
    thumbnail toggle ON must still render no image (claim type alone can't gate imagery)."""
    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    _case_with_thumb(schema, subject, claim="copyright",
                     page_url="https://foo.example/gallery/pic", sensitive=True)

    with tenant_session(schema) as s:
        rows = reports_svc.gather_case_rows(s, subject_id=None, include_thumbnails=True)
    assert rows[0].url == "https://foo.example/gallery/pic"  # full URL for non-ncii
    assert rows[0].thumbnail is None  # sensitive → default-deny, no image


def test_cleared_case_renders_thumbnail_only_when_toggled(
    db: Fixtures, new_workspace
) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    _case_with_thumb(schema, subject, claim="copyright",
                     page_url="https://foo.example/gallery/pic", sensitive=False)

    with tenant_session(schema) as s:
        off = reports_svc.gather_case_rows(s, subject_id=None, include_thumbnails=False)
        on = reports_svc.gather_case_rows(s, subject_id=None, include_thumbnails=True)
    assert off[0].thumbnail is None  # toggle off → no image even when not sensitive
    assert on[0].thumbnail == b"\x89PNGfakebytes"  # cleared + toggled → image renders


def test_ncii_case_cannot_be_cleared(db: Fixtures, new_workspace) -> None:
    from api.app.services import cases as cases_svc

    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    cid = _case_with_thumb(schema, subject, claim="ncii", page_url="https://bad.example/x")
    with tenant_session(schema) as s:
        case = cases_svc.get_case(s, cid)
        with pytest.raises(cases_svc.CasePreconditionFailed):
            cases_svc.clear_sensitive(
                s, workspace_id=new_workspace.id, actor_staff_id=db.admin_staff_id, case=case
            )


def test_reclassifying_a_cleared_case_to_ncii_re_hides_imagery(
    db: Fixtures, new_workspace
) -> None:
    """change_claim is a second door onto `sensitive` — reclassifying a cleared copyright case to
    ncii must re-hide its imagery (defense against the exact leak this flag exists to close)."""
    from api.app.services import cases as cases_svc

    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    cid = _case_with_thumb(schema, subject, claim="copyright",
                           page_url="https://foo.example/pic", sensitive=False)
    with tenant_session(schema) as s:
        case = cases_svc.get_case(s, cid)
        # Cleared copyright: image would render...
        on = reports_svc.gather_case_rows(s, subject_id=None, include_thumbnails=True)
        assert on[0].thumbnail is not None
        # ...but reclassifying to ncii forces sensitive back on.
        cases_svc.change_claim(
            s, workspace_id=new_workspace.id, actor_staff_id=db.admin_staff_id, case=case,
            new_claim_type="ncii", note="actually intimate content",
        )
        assert case.sensitive is True
        rows = reports_svc.gather_case_rows(s, subject_id=None, include_thumbnails=True)
    assert rows[0].thumbnail is None  # no image after reclassification
    assert rows[0].url == "foo.example"  # and ncii URL redaction now applies


def test_per_subject_report_excludes_other_subjects(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    a = make_subject(schema, enforcement_consent=True)
    b = make_subject(schema, enforcement_consent=True)
    _case_with_thumb(schema, a, claim="copyright", page_url="https://a.example/one")
    _case_with_thumb(schema, b, claim="copyright", page_url="https://b.example/two")

    with tenant_session(schema) as s:
        rows = reports_svc.gather_case_rows(s, subject_id=a, include_thumbnails=True)
        m = metrics_svc.report_metrics(
            s, subject_id=a, start=START, end=END, as_of=datetime.now(UTC)
        )
    urls = {r.url for r in rows}
    assert urls == {"https://a.example/one"}  # B's case absent
    assert "https://b.example/two" not in urls
    # The per-subject funnel only sees subject A's single open case.
    assert m.open_cases_by_status == {"confirmed": 1}


def test_list_inbox_stamps_shown_at_once(db: Fixtures, new_workspace) -> None:
    """review.list_inbox stamps shown_at the first time and never overwrites it."""
    from api.app.services import review as review_svc

    schema = new_workspace.schema_name
    subject = make_subject(schema, enforcement_consent=True)
    with tenant_session(schema) as s:
        cand = DiscoveryCandidate(
            subject_id=subject, provider="serpapi", kind=CandidateKind.link,
            source_url="https://pending.example/x", source_key="pending-x",
            review_status=ReviewStatus.pending,
        )
        s.add(cand)
        s.flush()
        cand_id = cand.id

    with tenant_session(schema) as s:
        review_svc.list_inbox(s)  # first view stamps
    with tenant_session(schema) as s:
        first = s.get(DiscoveryCandidate, cand_id).shown_at
    assert first is not None

    with tenant_session(schema) as s:
        review_svc.list_inbox(s)  # second view must not move it
    with tenant_session(schema) as s:
        assert s.get(DiscoveryCandidate, cand_id).shown_at == first
