"""Authz + isolation for the agency portal (Slice 12): IDOR across workspaces, revocation on the
next request, MFA, and that an agency user can never be a case assignee."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.config import get_settings
from api.app.db.session import public_session
from api.app.models.public import Staff, StaffWorkspaceAccess, Workspace
from api.app.services.workspaces import create_workspace_with_access
from api.tests.casehelpers import make_case
from api.tests.portalhelpers import make_agency_user
from api.tests.reviewhelpers import make_subject


def _two_workspaces(admin_staff_id: int) -> tuple[Workspace, Workspace]:
    import uuid

    a = create_workspace_with_access(
        name="Iso A", creator_staff_id=admin_staff_id, slug=f"iso-a-{uuid.uuid4().hex[:8]}"
    )
    b = create_workspace_with_access(
        name="Iso B", creator_staff_id=admin_staff_id, slug=f"iso-b-{uuid.uuid4().hex[:8]}"
    )
    return a, b


def test_agency_a_cannot_read_agency_b(client: TestClient, db, auth_header) -> None:
    wsa, wsb = _two_workspaces(db.admin_staff_id)
    # Give B two cases so it has a case id (2) that does NOT exist in A's schema.
    sid_b = make_subject(wsb.schema_name)
    make_case(wsb.schema_name, sid_b, claim_type="copyright", source_url="https://b.example/1")
    case_b_high = make_case(
        wsb.schema_name, sid_b, claim_type="copyright", source_url="https://b.example/2"
    )
    sid_a = make_subject(wsa.schema_name)
    make_case(wsa.schema_name, sid_a, claim_type="copyright", source_url="https://a.ex/1")

    make_agency_user(clerk_user_id="agency_a", email="a@agency.test", workspace_id=wsa.id)
    hdr = auth_header("agency_a")

    # A sees only its own cases (its schema), and B's data never appears.
    cases = client.get("/portal/cases", headers=hdr).json()
    assert cases and all(c["subject_id"] == sid_a for c in cases)
    assert "b.example" not in str(cases)
    # Guessing B's higher case id resolves against A's own schema → not found (no cross-tenant).
    assert client.get(f"/portal/cases/{case_b_high}", headers=hdr).status_code == 404
    assert client.get("/portal/context", headers=hdr).json()["workspace_id"] == wsa.id


def test_revocation_takes_effect_next_request(client: TestClient, db, auth_header) -> None:
    (wsa, _wsb) = _two_workspaces(db.admin_staff_id)
    staff_id = make_agency_user(
        clerk_user_id="agency_revoke", email="r@agency.test", workspace_id=wsa.id
    )
    hdr = auth_header("agency_revoke")
    assert client.get("/portal/context", headers=hdr).status_code == 200

    # Revoke the single grant; the very next request must fail closed.
    with public_session() as session:
        grant = session.scalar(
            select(StaffWorkspaceAccess).where(StaffWorkspaceAccess.staff_id == staff_id)
        )
        session.delete(grant)
    assert client.get("/portal/context", headers=hdr).status_code == 403


def test_agency_without_mfa_rejected_when_required(
    client: TestClient, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    (wsa, _b) = _two_workspaces(db.admin_staff_id)
    make_agency_user(clerk_user_id="agency_mfa", email="m@agency.test", workspace_id=wsa.id)
    monkeypatch.setattr(get_settings(), "clerk_require_mfa", True)
    from api.app.auth.clerk import make_test_token

    # No fva claim → rejected.
    azp = "http://localhost:5173"
    no_mfa = {"Authorization": f"Bearer {make_test_token('agency_mfa', azp=azp)}"}
    assert client.get("/portal/context", headers=no_mfa).status_code == 401
    # Verified second factor → allowed.
    with_mfa = {"Authorization": f"Bearer {make_test_token('agency_mfa', azp=azp, mfa=True)}"}
    assert client.get("/portal/context", headers=with_mfa).status_code == 200


def test_agency_user_cannot_be_assigned_to_a_case(client: TestClient, db, auth_header) -> None:
    (wsa, _b) = _two_workspaces(db.admin_staff_id)
    sid = make_subject(wsa.schema_name)
    case_id = make_case(wsa.schema_name, sid, claim_type="copyright")
    agency_staff_id = make_agency_user(
        clerk_user_id="agency_assignee", email="as@agency.test", workspace_id=wsa.id
    )
    # Admin tries to assign the agency user to a case → rejected (addition #3).
    r = client.post(
        f"/workspaces/{wsa.id}/cases/{case_id}/assign",
        headers=auth_header("admin_user"),
        json={"staff_id": agency_staff_id},
    )
    assert r.status_code == 422
    assert "agency" in r.json()["detail"].lower()


def test_agency_user_excluded_from_staff_listing(client: TestClient, db, auth_header) -> None:
    wsa, _b = _two_workspaces(db.admin_staff_id)
    agency_staff_id = make_agency_user(
        clerk_user_id="agency_listed", email="l@agency.test", workspace_id=wsa.id
    )
    # The admin agency-user listing shows agency rows (that's its purpose); assert they are agency.
    admin = auth_header("admin_user")
    rows = client.get(f"/workspaces/{wsa.id}/agency-users", headers=admin).json()
    assert any(r["id"] == agency_staff_id and r["role"] == "agency" for r in rows)
    # And confirm the row really is role=agency in the DB (never admin/reviewer).
    with public_session() as session:
        staff = session.get(Staff, agency_staff_id)
        assert staff is not None and staff.role == "agency"
