"""In-memory billing backend for dev/test. Never touches the network.

Deterministic and inspectable: tests seed subscriptions/prices and read back the recorded calls.
Webhook signatures use a plain HMAC over the raw payload keyed on STRIPE_WEBHOOK_SECRET, so a test
can forge an invalid signature (→ SignatureError) or sign a valid one via ``fake_sign``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field

from api.app.billing.client import (
    CheckoutSession,
    SignatureError,
    SubscriptionView,
    WebhookEvent,
)
from api.app.config import get_settings


def fake_sign(payload: bytes, secret: str) -> str:
    """The signature the fake backend accepts for ``payload`` (test helper)."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


@dataclass
class FakeBillingBackend:
    customers: dict[str, dict] = field(default_factory=dict)
    subscriptions: dict[str, SubscriptionView] = field(default_factory=dict)
    prices: dict[str, int] = field(default_factory=dict)
    credits: dict[str, int] = field(default_factory=dict)  # idempotency_key -> amount
    coupons: list[tuple[str, str]] = field(default_factory=list)  # (subscription_id, coupon_id)
    quantity_sets: list[tuple[str, int]] = field(default_factory=list)
    checkouts: list[dict] = field(default_factory=list)
    portals: list[dict] = field(default_factory=list)
    _seq: int = 0

    # ── test seams ────────────────────────────────────────────────────────────
    def seed_subscription(self, sub: SubscriptionView) -> None:
        self.subscriptions[sub.id] = sub

    def seed_price(self, price_id: str, amount: int) -> None:
        self.prices[price_id] = amount

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_fake_{self._seq}"

    # ── BillingClient ───────────────────────────────────────────────────────────
    def create_customer(self, *, workspace_id: int, email: str | None, name: str) -> str:
        cid = self._next("cus")
        self.customers[cid] = {"workspace_id": workspace_id, "email": email, "name": name}
        return cid

    def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        quantity: int,
        success_url: str,
        cancel_url: str,
        automatic_tax: bool,
    ) -> CheckoutSession:
        sid = self._next("cs")
        self.checkouts.append(
            {
                "mode": "subscription",
                "customer_id": customer_id,
                "price_id": price_id,
                "quantity": quantity,
                "automatic_tax": automatic_tax,
            }
        )
        return CheckoutSession(id=sid, url=f"https://fake.stripe.test/checkout/{sid}")

    def create_payment_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax: bool,
    ) -> CheckoutSession:
        sid = self._next("cs")
        self.checkouts.append(
            {
                "mode": "payment",
                "customer_id": customer_id,
                "price_id": price_id,
                "automatic_tax": automatic_tax,
            }
        )
        return CheckoutSession(id=sid, url=f"https://fake.stripe.test/checkout/{sid}")

    def create_portal_session(
        self, *, customer_id: str, configuration_id: str | None, return_url: str
    ) -> str:
        pid = self._next("bps")
        self.portals.append(
            {"customer_id": customer_id, "configuration_id": configuration_id}
        )
        return f"https://fake.stripe.test/portal/{pid}"

    def get_subscription(self, subscription_id: str) -> SubscriptionView:
        sub = self.subscriptions.get(subscription_id)
        if sub is None:
            # Treat an unknown/deleted subscription as canceled (re-fetch truth).
            return SubscriptionView(
                id=subscription_id,
                status="canceled",
                price_id=None,
                quantity=0,
                current_period_end=None,
            )
        return sub

    def set_subscription_quantity(self, subscription_id: str, quantity: int) -> None:
        self.quantity_sets.append((subscription_id, quantity))
        sub = self.subscriptions.get(subscription_id)
        if sub is not None:
            self.subscriptions[subscription_id] = SubscriptionView(
                id=sub.id,
                status=sub.status,
                price_id=sub.price_id,
                quantity=quantity,
                current_period_end=sub.current_period_end,
            )

    def apply_coupon(self, *, subscription_id: str, coupon_id: str) -> None:
        self.coupons.append((subscription_id, coupon_id))

    def price_amount(self, price_id: str) -> int:
        return self.prices.get(price_id, 150_000)  # default $1,500 for the onboarding audit

    def credit_customer_balance(
        self, *, customer_id: str, amount: int, idempotency_key: str
    ) -> None:
        # Idempotent on the key: a repeat with the same key is a no-op.
        self.credits.setdefault(idempotency_key, amount)

    def construct_event(self, *, payload: bytes, signature: str) -> WebhookEvent:
        secret = get_settings().stripe_webhook_secret or "whsec_fake"
        expected = fake_sign(payload, secret)
        if not hmac.compare_digest(expected, signature or ""):
            raise SignatureError("invalid signature")
        try:
            doc = json.loads(payload.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise SignatureError("unparseable payload") from exc
        return WebhookEvent(
            id=str(doc.get("id", "")),
            type=str(doc.get("type", "")),
            data_object=dict(doc.get("data", {}).get("object", {})),
        )
