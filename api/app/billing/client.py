"""The billing backend protocol + shared value types.

The app never computes money: it only sets a subscription *quantity*, attaches coupons/credits, and
reads subscription state. All amounts/tiers/annual pricing live on Stripe Price objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class BillingError(Exception):
    """A billing backend failure."""


class SignatureError(BillingError):
    """The webhook signature did not verify."""


@dataclass(frozen=True)
class SubscriptionView:
    """The subset of a Stripe subscription the mirror needs. Stripe is the source of truth."""

    id: str
    status: str  # trialing | active | past_due | canceled | incomplete | ...
    price_id: str | None
    quantity: int
    current_period_end: datetime | None


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class WebhookEvent:
    id: str
    type: str
    # The event's primary object (subscription/session/invoice) as a plain dict.
    data_object: dict


class BillingClient(Protocol):
    """What services/billing.py needs from a billing backend. Implementations: Stripe + fake."""

    def create_customer(self, *, workspace_id: int, email: str | None, name: str) -> str:
        """Create a Stripe customer for the workspace; return its id."""
        ...

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
        ...

    def create_payment_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax: bool,
    ) -> CheckoutSession:
        """One-time payment Checkout (the onboarding audit), mode=payment."""
        ...

    def create_portal_session(
        self, *, customer_id: str, configuration_id: str | None, return_url: str
    ) -> str:
        """Billing-Portal session URL (card/ACH/invoices/cancel; config disables qty/plan)."""
        ...

    def get_subscription(self, subscription_id: str) -> SubscriptionView:
        ...

    def set_subscription_quantity(self, subscription_id: str, quantity: int) -> None:
        """Set the subscription quantity ABSOLUTELY (idempotent); Stripe-default proration."""
        ...

    def apply_coupon(self, *, subscription_id: str, coupon_id: str) -> None:
        ...

    def price_amount(self, price_id: str) -> int:
        """The unit amount (smallest currency unit) of a Price — for the onboarding credit."""
        ...

    def credit_customer_balance(
        self, *, customer_id: str, amount: int, idempotency_key: str
    ) -> None:
        """Apply a negative customer-balance credit (idempotent on the key)."""
        ...

    def construct_event(self, *, payload: bytes, signature: str) -> WebhookEvent:
        """Verify the webhook signature and return the parsed event, or raise SignatureError."""
        ...
