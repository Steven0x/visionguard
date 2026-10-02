"""Billing backend factory (Slice 13).

``fake`` records calls in-memory and never touches the network (dev/test); ``stripe`` talks to
Stripe and is required in deployments (see Settings._guard_deployed_env). Mirrors the
storage/fetcher/provider/capture/csam backend pattern.
"""

from __future__ import annotations

from functools import lru_cache

from api.app.billing.client import BillingClient
from api.app.config import get_settings


@lru_cache
def get_billing_client() -> BillingClient:
    settings = get_settings()
    if settings.billing_backend == "stripe":
        from api.app.billing.stripe_backend import StripeBackend

        return StripeBackend(settings)
    from api.app.billing.fake_backend import FakeBillingBackend

    return FakeBillingBackend()


__all__ = ["BillingClient", "get_billing_client"]
