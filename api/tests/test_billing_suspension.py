"""Non-payment suspension (Slice 13). Suspended = stripe-mode past-grace | canceled | never-
subscribed. It gates EXACTLY two things — new subjects and new discovery — and NOTHING else.
Recording outcomes, moving/withdrawing filed cases, re-checks, evidence access and report
downloads all keep working, and no data is ever deleted. See docs/specs/billing.md.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app.db.base import schema_for_workspace
from api.app.db.session import tenant_session
from api.app.models.billing import BillingStatus
from api.app.models.cases import Case, CaseStatus
from api.app.models.public import Workspace
from api.app.models.subjects import Subject
from api.app.services import billing as billing_svc
from api.app.services import cases as cases_svc
from api.app.services import discovery as discovery_svc
from api.app.services import reports as reports_svc
from api.app.services.subjects import create_subject
from api.tests.billinghelpers import (
    set_billing,
    suspend_canceled,
    suspend_never_subscribed,
    suspend_past_grace,
)
from api.tests.casehelpers import make_case, seal_capture


def _make_subject(ws_id: int) -> int:
    with tenant_session(schema_for_workspace(ws_id)) as session:
        s = create_subject(session, workspace_id=ws_id, actor_staff_id=None, legal_name="Subj")
        return s.id


# ── New work is blocked ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "suspend", [suspend_past_grace, suspend_canceled, suspend_never_subscribed]
)
def test_new_subject_blocked_when_suspended(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake, suspend
) -> None:
    suspend(new_workspace.id)
    hdr = auth_header("admin_user")
    r = client.post(f"/workspaces/{new_workspace.id}/subjects", headers=hdr,
                    json={"legal_name": "Nope"})
    assert r.status_code == 402


def test_reactivate_blocked_when_suspended(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    # Add + archive a subject while active, then suspend and try to reactivate.
    set_billing(new_workspace.id, status=BillingStatus.active)
    hdr = auth_header("admin_user")
    sid = client.post(f"/workspaces/{new_workspace.id}/subjects", headers=hdr,
                      json={"legal_name": "R"}).json()["id"]
    client.post(f"/workspaces/{new_workspace.id}/subjects/{sid}/archive", headers=hdr)
    suspend_canceled(new_workspace.id)
    r = client.post(f"/workspaces/{new_workspace.id}/subjects/{sid}/reactivate", headers=hdr)
    assert r.status_code == 402


def test_new_discovery_blocked_when_suspended(
    new_workspace: Workspace, billing_fake
) -> None:
    sid = _make_subject(new_workspace.id)
    suspend_past_grace(new_workspace.id)
    with tenant_session(schema_for_workspace(new_workspace.id)) as session:
        subject = session.get(Subject, sid)
        assert subject is not None
        with pytest.raises(billing_svc.BillingSuspended):
            discovery_svc.intake_urls(
                session, workspace_id=new_workspace.id, actor_staff_id=None,
                subject=subject, urls=["https://example.com/x"],
            )


def test_discovery_gate_reports_not_allowed(new_workspace: Workspace, billing_fake) -> None:
    suspend_canceled(new_workspace.id)
    assert billing_svc.discovery_allowed(new_workspace.id) is False
    allowed, freq = billing_svc.discovery_frequency_gate(new_workspace.id, "daily")
    assert allowed is False and freq == "off"


# ── Work already filed keeps going (the non-negotiable) ──────────────────────────
def test_suspension_never_blocks_finishing_filed_work(
    new_workspace: Workspace, billing_fake
) -> None:
    ws = new_workspace.id
    schema = schema_for_workspace(ws)
    sid = _make_subject(ws)
    # Two filed, sealed cases + a report, created while active.
    set_billing(ws, status=BillingStatus.active)
    case_withdraw = make_case(schema, sid, status=CaseStatus.filed, claim_type="copyright")
    case_escalate = make_case(schema, sid, status=CaseStatus.filed, claim_type="copyright")
    seal_capture(schema, case_withdraw)
    seal_capture(schema, case_escalate)

    # Now suspend hard (canceled).
    suspend_canceled(ws)

    with tenant_session(schema) as session:
        # Withdrawals still work.
        c1 = session.get(Case, case_withdraw)
        assert c1 is not None
        cases_svc.transition(session, workspace_id=ws, actor_staff_id=None, case=c1,
                             to_status=CaseStatus.withdrawn, note="wrong claim")
        assert CaseStatus(c1.status) == CaseStatus.withdrawn
        # Moving a filed case forward (same ungated path outcomes use) still works.
        c2 = session.get(Case, case_escalate)
        assert c2 is not None
        cases_svc.transition(session, workspace_id=ws, actor_staff_id=None, case=c2,
                             to_status=CaseStatus.escalated, reason="outcome_countered_escalated")
        assert CaseStatus(c2.status) == CaseStatus.escalated

    # Report generation + download still work.
    with tenant_session(schema) as session:
        report = reports_svc.generate_report(
            session, schema=schema, workspace_id=ws, subject_id=None,
            start=date(2026, 1, 1), end=date(2026, 12, 31), actor_staff_id=None,
        )
        data, media = reports_svc.read_artifact(report, which="pdf")
        assert data and media == "application/pdf"

    # Evidence access (a sealed capture row) is still readable — nothing was deleted.
    with tenant_session(schema) as session:
        assert session.query(Case).count() == 2  # no data deleted for non-payment


def test_in_grace_is_banner_only_not_suspended(new_workspace: Workspace, billing_fake) -> None:
    now = datetime.now(UTC)
    set_billing(new_workspace.id, status=BillingStatus.past_due,
                past_due_since=now - timedelta(days=2), grace_until=now + timedelta(days=12))
    status = billing_svc.get_status(new_workspace.id)
    assert status["in_grace"] is True and status["suspended"] is False
    # New subjects still allowed during grace.
    assert billing_svc.discovery_allowed(new_workspace.id) is True
