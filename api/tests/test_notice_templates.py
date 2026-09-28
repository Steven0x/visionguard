"""Template approval lifecycle: unapproved by default; admin-only approval; editing an approved
template bumps the version and resets it to unapproved."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.app.db.session import public_session
from api.app.models.channels import NoticeTemplate, TemplateApproval
from api.app.services.templates import approve_template, edit_template, get_template
from api.tests.conftest import Fixtures
from api.tests.noticehelpers import set_template_approval

Auth = Callable[..., dict[str, str]]


def test_templates_seed_unapproved(db: Fixtures) -> None:
    set_template_approval("copyright", "email", approved=False)
    with public_session() as session:
        t = get_template(session, claim_type="copyright", method="email")
        assert t.approval_status == TemplateApproval.unapproved


def test_editing_approved_template_resets_to_unapproved(db: Fixtures) -> None:
    with public_session() as session:
        t = get_template(session, claim_type="copyright", method="email")
        approve_template(session, template=t, admin_staff_id=1, approver_name="Counsel")
        assert t.approval_status == TemplateApproval.counsel_approved
        v0 = t.version
        edit_template(session, template=t, body_template=t.body_template + "\nX")
        assert t.approval_status == TemplateApproval.unapproved
        assert t.version == v0 + 1
        assert t.approved_by_staff_id is None and t.approved_at is None


def test_reviewer_cannot_approve_template(
    client: TestClient, db: Fixtures, auth_header: Auth
) -> None:
    with public_session() as session:
        tid = get_template(session, claim_type="copyright", method="web_form").id
    r = client.post(
        f"/notice-templates/{tid}/approve",
        headers=auth_header("reviewer_a"), json={"approver_name": "X"},
    )
    assert r.status_code == 403


def test_admin_approve_records_approver(
    client: TestClient, db: Fixtures, auth_header: Auth
) -> None:
    set_template_approval("copyright", "web_form", approved=False)
    with public_session() as session:
        tid = get_template(session, claim_type="copyright", method="web_form").id
    r = client.post(
        f"/notice-templates/{tid}/approve",
        headers=auth_header("admin_user"), json={"approver_name": "Jane Counsel"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_status"] == "counsel_approved"
    assert body["approver_name"] == "Jane Counsel"
    with public_session() as session:
        row = session.get(NoticeTemplate, tid)
        assert row is not None and row.approved_at is not None


def test_approving_identity_gated_claims_is_blocked(
    client: TestClient, db: Fixtures, auth_header: Auth
) -> None:
    # likeness/ncii/impersonation lack a send-time identity-verification gate → approval refused.
    for claim in ("likeness", "ncii", "impersonation"):
        set_template_approval(claim, "web_form", approved=False)
        with public_session() as session:
            tid = get_template(session, claim_type=claim, method="web_form").id
        r = client.post(
            f"/notice-templates/{tid}/approve",
            headers=auth_header("admin_user"), json={"approver_name": "Jane Counsel"},
        )
        assert r.status_code == 422, r.text
        assert "identity verification" in r.json()["detail"].lower()
        with public_session() as session:
            row = session.get(NoticeTemplate, tid)
            assert row is not None and row.approval_status == TemplateApproval.unapproved


def test_copyright_template_approval_allowed(
    client: TestClient, db: Fixtures, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=False)
    with public_session() as session:
        tid = get_template(session, claim_type="copyright", method="email").id
    r = client.post(
        f"/notice-templates/{tid}/approve",
        headers=auth_header("admin_user"), json={"approver_name": "Counsel"},
    )
    assert r.status_code == 200, r.text
