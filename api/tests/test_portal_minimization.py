"""Data minimization in portal responses (Slice 12, CLAUDE.md #7). One assertion per rule."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseEvent, CaseEventKind, CaseStatus
from api.app.models.public import Workspace
from api.tests.casehelpers import make_case
from api.tests.portalhelpers import make_agency_user
from api.tests.reviewhelpers import make_subject

_URL = "https://leak-tube.example/videos/victim-name?token=abc"


def _set_sensitive(schema: str, case_id: int, sensitive: bool) -> None:
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        case.sensitive = sensitive


def _portal(client: TestClient, new_workspace: Workspace, auth_header) -> dict:
    make_agency_user(
        clerk_user_id=f"agency_min_{new_workspace.id}",
        email="min@agency.test",
        workspace_id=new_workspace.id,
    )
    return auth_header(f"agency_min_{new_workspace.id}")


def test_ncii_case_is_domain_only_and_imageless(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema)
    make_case(schema, sid, claim_type="ncii", source_url=_URL)  # sensitive defaults TRUE
    hdr = _portal(client, new_workspace, auth_header)
    case = client.get("/portal/cases", headers=hdr).json()[0]
    assert case["display_url"] == "https://leak-tube.example"
    assert "victim-name" not in str(case) and "token=abc" not in str(case)
    # No image reference of any kind.
    assert not any("image" in k or "thumbnail" in k for k in case)


def test_sensitive_non_ncii_is_domain_only(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema)
    cid = make_case(schema, sid, claim_type="copyright", source_url=_URL)
    _set_sensitive(schema, cid, True)
    hdr = _portal(client, new_workspace, auth_header)
    case = client.get("/portal/cases", headers=hdr).json()[0]
    # Domain-only so the agency can still tell sensitive cases apart (addition #4).
    assert case["display_url"] == "https://leak-tube.example"


def test_non_sensitive_shows_full_url(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema)
    cid = make_case(schema, sid, claim_type="copyright", source_url=_URL)
    _set_sensitive(schema, cid, False)
    hdr = _portal(client, new_workspace, auth_header)
    case = client.get("/portal/cases", headers=hdr).json()[0]
    assert case["display_url"] == _URL


def test_case_omits_internal_fields(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema)
    make_case(
        schema, sid, claim_type="copyright", source_url=_URL,
        offender_key="offender-123", page_url="https://leak-tube.example/page",
    )
    hdr = _portal(client, new_workspace, auth_header)
    case = client.get("/portal/cases", headers=hdr).json()[0]
    for internal in (
        "offender_key", "page_url", "assigned_staff_id", "opened_by_staff_id",
        "source_key", "removal_proposed_at", "reappearance_proposed_at",
        "removal_unverified_at", "sensitive", "matched_asset_id", "candidate_id",
    ):
        assert internal not in case
    assert set(case) == {
        "id", "subject_id", "claim_type", "status", "display_url",
        "created_at", "updated_at",
    }


def test_timeline_has_transitions_only_no_actor_or_notes(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema)
    cid = make_case(schema, sid, claim_type="copyright", source_url=_URL)
    with tenant_session(schema) as session:
        session.add(
            CaseEvent(
                case_id=cid, kind=CaseEventKind.transition,
                from_status=CaseStatus.confirmed, to_status=CaseStatus.filed,
                actor_staff_id=777, reason="internal-reason", note="internal reviewer note",
            )
        )
    hdr = _portal(client, new_workspace, auth_header)
    detail = client.get(f"/portal/cases/{cid}", headers=hdr).json()
    # Exact key allowlists — like the event check below. This catches a staff id (or any other
    # internal field) leaking under ANY name, and avoids the flaky value-substring match the old
    # `"999" not in str(detail)` used (short numbers collide with incidental digits in ids and
    # created_at microseconds, failing ~1% of full runs as ids grow).
    assert set(detail) == {"case", "timeline"}
    assert set(detail["case"]) == {
        "id",
        "subject_id",
        "claim_type",
        "status",
        "display_url",
        "created_at",
        "updated_at",
    }
    assert detail["timeline"], "expected a transition event"
    ev = detail["timeline"][0]
    assert set(ev) == {"from_status", "to_status", "created_at"}
    # Internal note/reason text must not appear inside an allowed field's value either.
    blob = str(detail)
    assert "internal reviewer note" not in blob and "internal-reason" not in blob


def test_reports_omit_internal_fields(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    from datetime import UTC, date, datetime

    from api.app.models.reports import Report

    schema = new_workspace.schema_name
    with tenant_session(schema) as session:
        session.add(
            Report(
                subject_id=None,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                as_of=datetime.now(UTC),
                include_thumbnails=False,
                pdf_key="k/report.pdf",
                pdf_sha256="a" * 64,
                json_key="k/inputs.json",
                json_sha256="b" * 64,
                generated_by_staff_id=999,
            )
        )
    hdr = _portal(client, new_workspace, auth_header)
    reports = client.get("/portal/reports", headers=hdr).json()
    assert reports and set(reports[0]) == {
        "id", "subject_id", "period_start", "period_end", "created_at",
    }
    assert "999" not in str(reports)  # no generated_by_staff_id / keys / hashes


def test_subject_omits_notes(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    with tenant_session(schema) as session:
        from api.app.models.subjects import Subject

        session.add(Subject(legal_name="Jane", notes="internal subject note"))
    hdr = _portal(client, new_workspace, auth_header)
    subjects = client.get("/portal/subjects", headers=hdr).json()
    assert subjects and "notes" not in subjects[0]
    assert "biometrics_blocked" not in subjects[0]
    assert "internal subject note" not in str(subjects)
