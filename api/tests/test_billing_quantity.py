"""Per-subject quantity sync (Slice 13): adding / archiving / reactivating a subject drives the
Stripe subscription quantity to max(active, min=5), absolutely and idempotently. No endpoint ever
accepts a quantity. Manual/none/canceled are no-ops. See docs/specs/billing.md."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.models.billing import BillingMode, BillingStatus
from api.app.models.public import Workspace
from api.tests.billinghelpers import set_billing


def _add_subject(client: TestClient, hdr: dict, ws_id: int, name: str) -> int:
    r = client.post(
        f"/workspaces/{ws_id}/subjects", headers=hdr, json={"legal_name": name}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_adds_above_min_drive_quantity(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active, quantity=5)
    hdr = auth_header("admin_user")
    # First 5 subjects stay at the min floor (desired == 5 == observed → no Stripe write).
    ids = [_add_subject(client, hdr, new_workspace.id, f"S{i}") for i in range(5)]
    assert billing_fake.quantity_sets == []  # at/below the floor → no Stripe write
    # The 6th add pushes the active count past the floor → quantity 6.
    _add_subject(client, hdr, new_workspace.id, "S5")
    assert billing_fake.quantity_sets[-1][1] == 6

    # Archiving back below the floor returns to 5 (never below the minimum).
    r = client.post(
        f"/workspaces/{new_workspace.id}/subjects/{ids[0]}/archive", headers=hdr
    )
    assert r.status_code == 200
    assert billing_fake.quantity_sets[-1][1] == 5


def test_reactivate_rebills(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active, quantity=6)
    hdr = auth_header("admin_user")
    ids = [_add_subject(client, hdr, new_workspace.id, f"R{i}") for i in range(6)]  # 6 active
    client.post(f"/workspaces/{new_workspace.id}/subjects/{ids[0]}/archive", headers=hdr)
    assert billing_fake.quantity_sets[-1][1] == 5
    # Reactivate → back to 6 active → quantity 6.
    r = client.post(
        f"/workspaces/{new_workspace.id}/subjects/{ids[0]}/reactivate", headers=hdr
    )
    assert r.status_code == 200
    assert billing_fake.quantity_sets[-1][1] == 6


def test_manual_mode_is_a_noop(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    set_billing(new_workspace.id, mode=BillingMode.manual, seed_sub=False,
                subscription_id=None, customer_id=None)
    hdr = auth_header("admin_user")
    for i in range(7):
        _add_subject(client, hdr, new_workspace.id, f"M{i}")
    assert billing_fake.quantity_sets == []  # never touches Stripe in manual mode


def test_no_endpoint_accepts_a_quantity(
    client: TestClient, new_workspace: Workspace, auth_header, billing_fake
) -> None:
    set_billing(new_workspace.id, status=BillingStatus.active, quantity=5)
    hdr = auth_header("admin_user")
    # A client-supplied quantity is ignored by the checkout schema (extra field, not honored).
    r = client.post(
        f"/workspaces/{new_workspace.id}/billing/checkout",
        headers=hdr,
        json={"plan_tier": "core", "cadence": "monthly", "quantity": 999},
    )
    assert r.status_code == 200
    # The checkout was created with the DERIVED quantity (5), not 999.
    assert billing_fake.checkouts[-1]["quantity"] == 5
