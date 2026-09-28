"""Reopen-on-reappearance (Slice 9): the monitoring matcher (account vs host+asset, never
domain-merge on a platform), the re-checked guards, and the fresh-approval requirement."""

from __future__ import annotations

import pytest

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.discovery import DiscoveryCandidate
from api.app.models.notices import Notice, NoticeStatus
from api.app.models.subjects import AllowlistKind, Subject
from api.app.services import cases as cases_svc
from api.app.services import notices as notices_svc
from api.app.services import review as review_svc
from api.app.services.offender import offender_key
from api.tests.casehelpers import load, make_case
from api.tests.conftest import Fixtures
from api.tests.noticehelpers import add_copyright_rights
from api.tests.reviewhelpers import add_allowlist, add_asset, add_candidate, make_subject


def _monitoring_case(schema: str, subject: int, *, page_url: str, asset_id: int | None = None,
                     claim: str = "likeness") -> int:
    return make_case(
        schema, subject, status=CaseStatus.monitoring, claim_type=claim,
        source_url=page_url, page_url=page_url, offender_key=offender_key(page_url),
        matched_asset_id=asset_id,
    )


# ── Matcher ──────────────────────────────────────────────────────────────────


def test_matcher_same_platform_account_merges(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    _monitoring_case(schema, subject, page_url="https://instagram.com/bob/p/1")
    cand = add_candidate(schema, subject, source_url="https://instagram.com/bob/p/2",
                         page_url="https://instagram.com/bob/p/2")
    with tenant_session(schema) as s:
        candidate = load(s, DiscoveryCandidate, cand)
        match = cases_svc.find_monitoring_case(s, subject_id=subject, candidate=candidate)
        assert match is not None


def test_matcher_different_account_same_platform_no_merge(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    asset = add_asset(schema, subject)
    _monitoring_case(schema, subject, page_url="https://instagram.com/alice/p/1", asset_id=asset)
    # A different account on the SAME platform, even with the same matched asset, is a distinct
    # offence — a platform host must never domain-merge.
    cand = add_candidate(schema, subject, source_url="https://instagram.com/bob/p/9",
                         page_url="https://instagram.com/bob/p/9", best_match_asset_id=asset)
    with tenant_session(schema) as s:
        candidate = load(s, DiscoveryCandidate, cand)
        match = cases_svc.find_monitoring_case(s, subject_id=subject, candidate=candidate)
        assert match is None


def test_matcher_host_plus_asset_merges_for_nonplatform(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    asset = add_asset(schema, subject)
    _monitoring_case(schema, subject, page_url="https://leak.example/a", asset_id=asset)
    cand = add_candidate(schema, subject, source_url="https://leak.example/b",
                         page_url="https://leak.example/b", best_match_asset_id=asset)
    with tenant_session(schema) as s:
        candidate = load(s, DiscoveryCandidate, cand)
        match = cases_svc.find_monitoring_case(s, subject_id=subject, candidate=candidate)
        assert match is not None


def test_matcher_same_host_different_asset_does_not_merge(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    asset_a = add_asset(schema, subject)
    asset_b = add_asset(schema, subject)
    _monitoring_case(schema, subject, page_url="https://leak.example/a", asset_id=asset_a)
    cand = add_candidate(schema, subject, source_url="https://leak.example/b",
                         page_url="https://leak.example/b", best_match_asset_id=asset_b)
    with tenant_session(schema) as s:
        candidate = load(s, DiscoveryCandidate, cand)
        assert cases_svc.find_monitoring_case(s, subject_id=subject, candidate=candidate) is None


def test_matcher_different_reddit_users_no_merge(db: Fixtures, new_workspace) -> None:
    # reddit.com/user/<x> — the account is NOT the first path segment, so it must not collapse two
    # different users to one offender key (regression guard for the reopen matcher).
    schema = new_workspace.schema_name
    subject = make_subject(schema)
    asset = add_asset(schema, subject)
    _monitoring_case(schema, subject, page_url="https://reddit.com/user/alice/comments/1",
                     asset_id=asset)
    cand = add_candidate(
        schema, subject, source_url="https://reddit.com/user/bob/comments/2",
        page_url="https://reddit.com/user/bob/comments/2", best_match_asset_id=asset,
    )
    with tenant_session(schema) as s:
        candidate = load(s, DiscoveryCandidate, cand)
        match = cases_svc.find_monitoring_case(s, subject_id=subject, candidate=candidate)
        assert match is None


# ── Confirm routes a reappearance into a reopen, not a duplicate ───────────────


def test_confirm_reopens_monitoring_instead_of_new_case(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, authorized=True, enforcement_consent=True)  # supports likeness
    case_id = _monitoring_case(schema, subject, page_url="https://instagram.com/bob/p/1")
    cand = add_candidate(schema, subject, source_url="https://instagram.com/bob/p/2",
                         page_url="https://instagram.com/bob/p/2")
    with tenant_session(schema) as s:
        subj = load(s, Subject, subject)
        candidate = load(s, DiscoveryCandidate, cand)
        case = review_svc.confirm_candidate(
            s, workspace_id=new_workspace.id, actor_staff_id=1, subject=subj,
            candidate=candidate, claim_type="likeness",
        )
        assert case.id == case_id  # reopened the SAME case
    with tenant_session(schema) as s:
        cases = s.query(Case).all()
        assert len(cases) == 1  # no duplicate
        assert cases[0].status == CaseStatus.confirmed
        assert cases[0].candidate_id == cand  # points at the reappearance


def test_confirm_opens_new_case_for_different_account(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, authorized=True, enforcement_consent=True)
    _monitoring_case(schema, subject, page_url="https://instagram.com/alice/p/1")
    cand = add_candidate(schema, subject, source_url="https://instagram.com/bob/p/2",
                         page_url="https://instagram.com/bob/p/2")
    with tenant_session(schema) as s:
        subj = load(s, Subject, subject)
        candidate = load(s, DiscoveryCandidate, cand)
        review_svc.confirm_candidate(
            s, workspace_id=new_workspace.id, actor_staff_id=1, subject=subj,
            candidate=candidate, claim_type="likeness",
        )
    with tenant_session(schema) as s:
        assert len(s.query(Case).all()) == 2  # distinct offences


# ── Guards ─────────────────────────────────────────────────────────────────


def test_reopen_refuses_when_allowlisted(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, authorized=True, enforcement_consent=True)
    case_id = _monitoring_case(schema, subject, page_url="https://leak.example/a")
    cand = add_candidate(schema, subject, source_url="https://leak.example/a",
                         page_url="https://leak.example/a")
    add_allowlist(schema, AllowlistKind.domain, "leak.example")
    with tenant_session(schema) as s:
        subj = load(s, Subject, subject)
        candidate = load(s, DiscoveryCandidate, cand)
        case = load(s, Case, case_id)
        with pytest.raises(cases_svc.CasePreconditionFailed):
            cases_svc.reopen_case(
                s, workspace_id=new_workspace.id, actor_staff_id=1, subject=subj,
                candidate=candidate, case=case,
            )


def test_reopened_case_requires_a_fresh_approval(db: Fixtures, new_workspace) -> None:
    schema = new_workspace.schema_name
    subject = make_subject(schema, authorized=True)
    add_copyright_rights(schema, subject)
    cand = add_candidate(schema, subject, source_url="https://leak.example/a",
                         page_url="https://leak.example/a")
    case_id = make_case(
        schema, subject, status=CaseStatus.monitoring, claim_type="copyright",
        source_url="https://leak.example/a", page_url="https://leak.example/a",
        offender_key=offender_key("https://leak.example/a"), candidate_id=cand,
    )
    # A prior (now-historical) filing on this case.
    with tenant_session(schema) as s:
        s.add(Notice(
            case_id=case_id, channel_id=1, template_id=1, template_version=1,
            claim_type="copyright", method="email", platform="generic_host",
            destination="a@b.invalid", status=NoticeStatus.sent,
        ))

    with tenant_session(schema) as s:
        subj = load(s, Subject, subject)
        candidate = load(s, DiscoveryCandidate, cand)
        case = load(s, Case, case_id)
        cases_svc.reopen_case(
            s, workspace_id=new_workspace.id, actor_staff_id=1, subject=subj,
            candidate=candidate, case=case,
        )
    # The reopened (Confirmed) case drafts a NEW notice needing a fresh approval.
    with tenant_session(schema) as s:
        case = load(s, Case, case_id)
        assert case.status == CaseStatus.confirmed
        notice = notices_svc.create_draft(
            s, workspace_id=new_workspace.id, actor_staff_id=1, case=case, platform="generic_host",
        )
        assert notice.status == NoticeStatus.draft
        assert notice.approved_at is None and notice.approved_by_staff_id is None
