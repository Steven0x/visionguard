"""Helpers for Slice 13 billing tests: put a workspace into a Stripe billing state + seed the fake
subscription, and build signed webhook payloads."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import cast

from api.app.billing import get_billing_client
from api.app.billing.client import SubscriptionView
from api.app.billing.fake_backend import FakeBillingBackend, fake_sign
from api.app.config import get_settings
from api.app.db.session import public_session
from api.app.models.billing import (
    BillingCadence,
    BillingMode,
    BillingStatus,
    PlanTier,
)
from api.app.services.billing import get_or_create


def set_billing(
    workspace_id: int,
    *,
    mode: BillingMode = BillingMode.stripe,
    status: BillingStatus = BillingStatus.active,
    plan_tier: PlanTier = PlanTier.core,
    cadence: BillingCadence = BillingCadence.monthly,
    quantity: int = 5,
    customer_id: str | None = "",
    subscription_id: str | None = "",
    price_id: str = "price_core_m",
    past_due_since: datetime | None = None,
    grace_until: datetime | None = None,
    billing_contact_staff_id: int | None = None,
    seed_sub: bool = True,
) -> None:
    """Write the mirror row and (optionally) seed the matching fake Stripe subscription.

    ``customer_id``/``subscription_id`` default to workspace-unique values ("" sentinel) so the
    unique-customer constraint never collides across the session-scoped shared DB. Pass ``None``
    explicitly for the never-subscribed case.
    """
    if customer_id == "":
        customer_id = f"cus_{workspace_id}"
    if subscription_id == "":
        subscription_id = f"sub_{workspace_id}"
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        billing.billing_mode = mode
        billing.status = status
        billing.plan_tier = plan_tier
        billing.cadence = cadence
        billing.quantity = quantity
        billing.stripe_customer_id = customer_id
        billing.stripe_subscription_id = subscription_id
        billing.past_due_since = past_due_since
        billing.grace_until = grace_until
        billing.billing_contact_staff_id = billing_contact_staff_id
        session.flush()
    if seed_sub and subscription_id:
        cast(FakeBillingBackend, get_billing_client()).seed_subscription(
            SubscriptionView(
                id=subscription_id,
                status=str(status),
                price_id=price_id,
                quantity=quantity,
                current_period_end=datetime.now(UTC) + timedelta(days=30),
            )
        )


def suspend_past_grace(workspace_id: int) -> None:
    """A past_due workspace whose grace window has already elapsed → suspended."""
    now = datetime.now(UTC)
    set_billing(
        workspace_id,
        status=BillingStatus.past_due,
        past_due_since=now - timedelta(days=60),
        grace_until=now - timedelta(days=46),
    )


def suspend_canceled(workspace_id: int) -> None:
    set_billing(workspace_id, status=BillingStatus.canceled)


def suspend_never_subscribed(workspace_id: int) -> None:
    set_billing(
        workspace_id,
        status=BillingStatus.none,
        subscription_id=None,
        customer_id=None,
        seed_sub=False,
    )


def webhook(event_id: str, event_type: str, obj: dict) -> tuple[bytes, dict[str, str]]:
    """A signed webhook (payload bytes + headers) the fake backend will accept."""
    payload = json.dumps(
        {"id": event_id, "type": event_type, "data": {"object": obj}}
    ).encode()
    sig = fake_sign(payload, get_settings().stripe_webhook_secret)
    return payload, {"stripe-signature": sig, "content-type": "application/json"}
