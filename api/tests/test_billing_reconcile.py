"""Daily billing reconciliation (Slice 13): for every stripe-mode workspace, re-fetch the
subscription and re-sync quantity + status, correcting drift (the missed/out-of-order webhook
safety net). Runs under the single-beat Redis lock. See docs/specs/billing.md."""

from __future__ import annotations

from fastapi.testclient import TestClient
from worker.billing import reconcile_billing

from api.app.billing.client import SubscriptionView
from api.app.db.session import public_session
from api.app.models.billing import BillingStatus, WorkspaceBilling
from api.app.models.public import Workspace
from api.app.services import billing as billing_svc
from api.tests.billinghelpers import set_billing


def test_reconcile_corrects_quantity_drift(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    ws = new_workspace.id
    # Stripe drifted to quantity 2; workspace has 0 active subjects → desired 5.
    set_billing(ws, status=BillingStatus.active, quantity=2)
    billing_fake.seed_subscription(
        SubscriptionView(id=f"sub_{ws}", status="active", price_id="price_core_m",
                         quantity=2, current_period_end=None)
    )
    corrected = reconcile_billing()
    assert corrected >= 1
    assert billing_fake.quantity_sets[-1][1] == 5
    with public_session() as session:
        row = session.get(WorkspaceBilling, ws)
        assert row is not None and row.quantity == 5


def test_reconcile_single_workspace_helper(new_workspace: Workspace, billing_fake) -> None:
    ws = new_workspace.id
    set_billing(ws, status=BillingStatus.active, quantity=9)
    billing_fake.seed_subscription(
        SubscriptionView(id=f"sub_{ws}", status="active", price_id="price_core_m",
                         quantity=9, current_period_end=None)
    )
    assert billing_svc.reconcile_workspace(ws) is True  # 9 → 5 (no active subjects)
    assert billing_fake.quantity_sets[-1][1] == 5
