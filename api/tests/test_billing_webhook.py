"""Stripe webhook (Slice 13): signature-gated, idempotent on event id, and it NEVER trusts the
event payload's state — it re-fetches the subscription from Stripe, so out-of-order events can't
regress the mirror and a wrong quantity is corrected. See docs/specs/billing.md."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.billing.client import SubscriptionView
from api.app.db.base import schema_for_workspace
from api.app.db.session import public_session, tenant_session
from api.app.models.audit import AuditLog
from api.app.models.billing import BillingStatus, WorkspaceBilling
from api.app.models.public import Workspace
from api.tests.billinghelpers import set_billing, webhook


def _mirror(workspace_id: int) -> WorkspaceBilling:
    with public_session() as session:
        b = session.get(WorkspaceBilling, workspace_id)
        assert b is not None
        session.expunge(b)
        return b


def _audit_actions(workspace_id: int) -> list[str]:
    with tenant_session(schema_for_workspace(workspace_id)) as session:
        return [a.action for a in session.query(AuditLog).all()]


def test_forged_signature_is_rejected_and_changes_nothing(
    client: TestClient, new_workspace: Workspace, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active, customer_id="cus_f")
    payload, headers = webhook(
        "evt_forge", "customer.subscription.updated",
        {"object": "subscription", "id": "sub_test", "customer": "cus_f"},
    )
    headers["stripe-signature"] = "deadbeef"  # wrong signature
    resp = client.post("/billing/webhook", content=payload, headers=headers)
    assert resp.status_code == 400
    assert _mirror(new_workspace.id).status == BillingStatus.active  # untouched


def test_replay_is_idempotent(
    client: TestClient, new_workspace: Workspace, billing_fake
) -> None:
    set_billing(new_workspace.id, customer_id="cus_r", subscription_id="sub_r")
    payload, headers = webhook(
        "evt_dup", "customer.subscription.updated",
        {"object": "subscription", "id": "sub_r", "customer": "cus_r"},
    )
    first = client.post("/billing/webhook", content=payload, headers=headers)
    second = client.post("/billing/webhook", content=payload, headers=headers)
    assert first.json()["result"] == "processed"
    assert second.json()["result"] == "duplicate"


def test_unknown_customer_is_ignored(
    client: TestClient, new_workspace: Workspace, billing_fake
) -> None:
    payload, headers = webhook(
        "evt_unknown", "customer.subscription.updated",
        {"object": "subscription", "id": "sub_x", "customer": "cus_does_not_exist"},
    )
    resp = client.post("/billing/webhook", content=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["result"] == "ignored"


def test_quantity_drift_is_corrected(
    client: TestClient, new_workspace: Workspace, billing_fake
) -> None:
    # Stripe currently reports quantity 3, but the workspace has 0 active subjects → desired 5.
    set_billing(
        new_workspace.id, status=BillingStatus.active, quantity=3,
        customer_id="cus_q", subscription_id="sub_q",
    )
    billing_fake.seed_subscription(
        SubscriptionView(id="sub_q", status="active", price_id="price_core_m",
                         quantity=3, current_period_end=None)
    )
    payload, headers = webhook(
        "evt_qty", "customer.subscription.updated",
        {"object": "subscription", "id": "sub_q", "customer": "cus_q"},
    )
    resp = client.post("/billing/webhook", content=payload, headers=headers)
    assert resp.status_code == 200
    assert billing_fake.quantity_sets[-1] == ("sub_q", 5)  # corrected back to the min floor
    assert _mirror(new_workspace.id).quantity == 5
    assert "billing.quantity_corrected" in _audit_actions(new_workspace.id)


def test_out_of_order_event_uses_refetched_truth(
    client: TestClient, new_workspace: Workspace, billing_fake
) -> None:
    # Mirror says active, but Stripe's CURRENT truth is canceled. A stale 'created' event must not
    # resurrect the subscription — we re-fetch and mirror the real (canceled) state.
    set_billing(new_workspace.id, status=BillingStatus.active,
                customer_id="cus_o", subscription_id="sub_o")
    billing_fake.seed_subscription(
        SubscriptionView(id="sub_o", status="canceled", price_id="price_core_m",
                         quantity=0, current_period_end=None)
    )
    payload, headers = webhook(
        "evt_stale", "customer.subscription.created",
        {"object": "subscription", "id": "sub_o", "customer": "cus_o"},
    )
    client.post("/billing/webhook", content=payload, headers=headers)
    assert _mirror(new_workspace.id).status == BillingStatus.canceled


def test_failed_apply_is_not_recorded_and_retry_succeeds(
    client: TestClient, new_workspace: Workspace, billing_fake, monkeypatch
) -> None:
    # If the re-fetch/apply fails mid-processing, the event id must NOT be recorded — otherwise
    # Stripe's retry would be swallowed as a duplicate and the update lost forever.
    set_billing(new_workspace.id, status=BillingStatus.active,
                customer_id="cus_flaky", subscription_id="sub_flaky")
    real = billing_fake.get_subscription
    calls = {"n": 0}

    def flaky(sub_id: str):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("stripe timeout")
        return real(sub_id)

    monkeypatch.setattr(billing_fake, "get_subscription", flaky)
    payload, headers = webhook(
        "evt_flaky", "customer.subscription.updated",
        {"object": "subscription", "id": "sub_flaky", "customer": "cus_flaky"},
    )
    first = client.post("/billing/webhook", content=payload, headers=headers)
    assert first.status_code == 500  # unhandled → caught as 500; event NOT recorded
    second = client.post("/billing/webhook", content=payload, headers=headers)
    assert second.status_code == 200 and second.json()["result"] == "processed"


def test_past_due_since_set_once_and_not_reset(
    client: TestClient, new_workspace: Workspace, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active,
                customer_id="cus_p", subscription_id="sub_p")
    billing_fake.seed_subscription(
        SubscriptionView(id="sub_p", status="past_due", price_id="price_core_m",
                         quantity=5, current_period_end=None)
    )
    p1, h1 = webhook("evt_pd1", "invoice.payment_failed",
                     {"object": "invoice", "subscription": "sub_p", "customer": "cus_p"})
    client.post("/billing/webhook", content=p1, headers=h1)
    first = _mirror(new_workspace.id).past_due_since
    assert first is not None and _mirror(new_workspace.id).grace_until is not None

    p2, h2 = webhook("evt_pd2", "invoice.payment_failed",
                     {"object": "invoice", "subscription": "sub_p", "customer": "cus_p"})
    client.post("/billing/webhook", content=p2, headers=h2)
    assert _mirror(new_workspace.id).past_due_since == first  # unchanged on the re-observation

    # A later invoice.paid (Stripe now reports active) clears past_due + the grace clock.
    billing_fake.seed_subscription(
        SubscriptionView(id="sub_p", status="active", price_id="price_core_m",
                         quantity=5, current_period_end=None)
    )
    p3, h3 = webhook("evt_paid", "invoice.paid",
                     {"object": "invoice", "subscription": "sub_p", "customer": "cus_p"})
    client.post("/billing/webhook", content=p3, headers=h3)
    after = _mirror(new_workspace.id)
    assert after.status == BillingStatus.active
    assert after.past_due_since is None and after.grace_until is None
