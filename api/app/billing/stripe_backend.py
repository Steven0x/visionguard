"""The real Stripe backend. The ``stripe`` SDK is imported lazily so dev/test (fake backend) never
need it installed. All pricing lives on Stripe Price objects — this backend only sets quantities and
attaches coupons/credits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from api.app.billing.client import (
    BillingError,
    CheckoutSession,
    SignatureError,
    SubscriptionView,
    WebhookEvent,
)
from api.app.config import Settings


def _stripe(settings: Settings) -> Any:
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


class StripeBackend:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stripe = _stripe(settings)

    def _sub_item(self, sub: Any) -> dict:
        items = sub["items"]["data"]
        if not items:
            raise BillingError(f"subscription {sub['id']} has no items")
        return items[0]

    def _view(self, sub: Any) -> SubscriptionView:
        item = self._sub_item(sub)
        return SubscriptionView(
            id=sub["id"],
            status=sub["status"],
            price_id=item["price"]["id"],
            quantity=int(item.get("quantity", 0)),
            current_period_end=_ts(sub.get("current_period_end")),
        )

    def create_customer(self, *, workspace_id: int, email: str | None, name: str) -> str:
        customer = self._stripe.Customer.create(
            email=email, name=name, metadata={"workspace_id": str(workspace_id)}
        )
        return customer["id"]

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
        session = self._stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": quantity}],
            payment_method_types=["card", "us_bank_account"],
            success_url=success_url,
            cancel_url=cancel_url,
            automatic_tax={"enabled": automatic_tax},
        )
        return CheckoutSession(id=session["id"], url=session["url"])

    def create_payment_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax: bool,
    ) -> CheckoutSession:
        session = self._stripe.checkout.Session.create(
            mode="payment",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            payment_method_types=["card", "us_bank_account"],
            success_url=success_url,
            cancel_url=cancel_url,
            automatic_tax={"enabled": automatic_tax},
        )
        return CheckoutSession(id=session["id"], url=session["url"])

    def create_portal_session(
        self, *, customer_id: str, configuration_id: str | None, return_url: str
    ) -> str:
        kwargs: dict[str, Any] = {"customer": customer_id, "return_url": return_url}
        if configuration_id:
            kwargs["configuration"] = configuration_id
        session = self._stripe.billing_portal.Session.create(**kwargs)
        return session["url"]

    def get_subscription(self, subscription_id: str) -> SubscriptionView:
        sub = self._stripe.Subscription.retrieve(subscription_id)
        return self._view(sub)

    def set_subscription_quantity(self, subscription_id: str, quantity: int) -> None:
        sub = self._stripe.Subscription.retrieve(subscription_id)
        item = self._sub_item(sub)
        # Modify the item quantity; Stripe-default proration.
        self._stripe.Subscription.modify(
            subscription_id, items=[{"id": item["id"], "quantity": quantity}]
        )

    def apply_coupon(self, *, subscription_id: str, coupon_id: str) -> None:
        self._stripe.Subscription.modify(subscription_id, coupon=coupon_id)

    def price_amount(self, price_id: str) -> int:
        price = self._stripe.Price.retrieve(price_id)
        amount = price.get("unit_amount")
        if amount is None:
            raise BillingError(f"price {price_id} has no unit_amount")
        return int(amount)

    def credit_customer_balance(
        self, *, customer_id: str, amount: int, idempotency_key: str
    ) -> None:
        # A negative balance transaction is a credit toward future invoices.
        self._stripe.Customer.create_balance_transaction(
            customer_id,
            amount=-abs(amount),
            currency="usd",
            description="VisionGuard onboarding audit credit",
            idempotency_key=idempotency_key,
        )

    def construct_event(self, *, payload: bytes, signature: str) -> WebhookEvent:
        try:
            event = self._stripe.Webhook.construct_event(
                payload, signature, self._settings.stripe_webhook_secret
            )
        except Exception as exc:  # stripe.error.SignatureVerificationError / ValueError
            raise SignatureError(str(exc)) from exc
        return WebhookEvent(
            id=event["id"],
            type=event["type"],
            data_object=dict(event["data"]["object"]),
        )
