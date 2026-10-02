"""Billing authz + tamper-resistance (Slice 13): only admins + the signature-gated webhook change
billing state; agency/reviewer can't. Billing contact is admin-set, must be an agency user of the
workspace, and only the contact can act in the portal. Feature limits + overrides. Audit coverage.
See docs/specs/billing.md."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.db.base import schema_for_workspace
from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.billing import BillingStatus, PlanTier
from api.app.models.public import Workspace
from api.app.services import billing as billing_svc
from api.tests.billinghelpers import set_billing
from api.tests.portalhelpers import make_agency_user


def _audits(ws_id: int) -> list[str]:
    with tenant_session(schema_for_workspace(ws_id)) as session:
        return [a.action for a in session.query(AuditLog).all()]


# ── Role gating ──────────────────────────────────────────────────────────────────
def test_reviewer_cannot_reach_billing_admin(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    # reviewer_a has access to workspace_a but is not admin; use a fresh ws the admin seeded.
    hdr = auth_header("reviewer_a")
    r = client.get(f"/workspaces/{new_workspace.id}/billing", headers=hdr)
    assert r.status_code == 403


def test_agency_cannot_reach_billing_admin(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    make_agency_user(clerk_user_id="ag_bill", email="ag@bill.test",
                     workspace_id=new_workspace.id)
    hdr = auth_header("ag_bill")
    r = client.put(f"/workspaces/{new_workspace.id}/billing/mode", headers=hdr,
                   json={"mode": "stripe"})
    assert r.status_code == 403


# ── Billing contact ──────────────────────────────────────────────────────────────
def test_billing_contact_must_be_agency_user_of_this_workspace(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    hdr = auth_header("admin_user")
    # An admin staff id is not an agency user → rejected (409).
    r = client.put(f"/workspaces/{new_workspace.id}/billing/billing-contact",
                   headers=hdr, json={"staff_id": 1})
    assert r.status_code == 409


def test_only_billing_contact_can_act_in_portal(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    contact = make_agency_user(clerk_user_id="ag_contact", email="c@bill.test",
                               workspace_id=new_workspace.id)
    make_agency_user(clerk_user_id="ag_other", email="o@bill.test",
                     workspace_id=new_workspace.id)
    set_billing(new_workspace.id, status=BillingStatus.active,
                billing_contact_staff_id=contact)

    # The non-contact agency user can read status but cannot create a checkout.
    other = auth_header("ag_other")
    assert client.get("/portal/billing", headers=other).json()["is_billing_contact"] is False
    r = client.post("/portal/billing/checkout", headers=other,
                    json={"plan_tier": "core", "cadence": "monthly"})
    assert r.status_code == 403

    # The designated contact can.
    cont = auth_header("ag_contact")
    r = client.post("/portal/billing/checkout", headers=cont,
                    json={"plan_tier": "core", "cadence": "monthly"})
    assert r.status_code == 200 and r.json()["url"]


# ── Feature limits + overrides ────────────────────────────────────────────────────
def test_core_capped_to_weekly_priority_allows_daily(
    new_workspace: Workspace, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active, plan_tier=PlanTier.core)
    _, freq = billing_svc.discovery_frequency_gate(new_workspace.id, "daily")
    assert freq == "weekly"  # Core clamps daily → weekly

    set_billing(new_workspace.id, status=BillingStatus.active, plan_tier=PlanTier.priority)
    _, freq = billing_svc.discovery_frequency_gate(new_workspace.id, "daily")
    assert freq == "daily"


def test_admin_override_forces_priority(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active, plan_tier=PlanTier.core)
    hdr = auth_header("admin_user")
    r = client.post(f"/workspaces/{new_workspace.id}/billing/override", headers=hdr,
                    json={"priority_override": True, "discovery_frequency_override": "daily"})
    assert r.status_code == 200
    _, freq = billing_svc.discovery_frequency_gate(new_workspace.id, "daily")
    assert freq == "daily"
    assert "billing.override_changed" in _audits(new_workspace.id)


# ── Onboarding credit idempotency ──────────────────────────────────────────────────
def test_onboarding_credit_is_applied_once(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active)
    billing_fake.seed_price("price_audit", 150_000)
    hdr = auth_header("admin_user")
    r1 = client.post(f"/workspaces/{new_workspace.id}/billing/onboarding-credit", headers=hdr)
    r2 = client.post(f"/workspaces/{new_workspace.id}/billing/onboarding-credit", headers=hdr)
    assert r1.status_code == 200 and r2.status_code == 200
    # Credit applied exactly once (idempotency key), amount from the price (not hard-coded).
    assert billing_fake.credits == {f"onboarding-credit:{new_workspace.id}": 150_000}
    assert _audits(new_workspace.id).count("billing.onboarding_credited") == 1


# ── Audit coverage ────────────────────────────────────────────────────────────────
def test_plan_changes_are_audited(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    hdr = auth_header("admin_user")
    client.put(f"/workspaces/{new_workspace.id}/billing/mode", headers=hdr,
               json={"mode": "stripe"})
    assert "billing.mode_changed" in _audits(new_workspace.id)
