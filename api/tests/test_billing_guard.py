"""The billing config guard (Slice 13): the fake backend is dev/test-only, a deployment requires
the real Stripe backend + keys + all plan prices, production needs LIVE keys, and a LIVE key is
refused outside production (staging must use TEST keys). See docs/specs/billing.md."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.app.config import Settings
from api.tests.deployhelpers import deployed_env


def test_fake_backend_refused_outside_dev_test(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("BILLING_BACKEND", "fake")
    with pytest.raises(ValidationError, match="BILLING_BACKEND=fake"):
        Settings()


def test_deployment_requires_stripe_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="staging")
    # An unknown backend value is rejected outright.
    monkeypatch.setenv("BILLING_BACKEND", "paypal")
    with pytest.raises(ValidationError, match="BILLING_BACKEND"):
        Settings()


def test_deployment_requires_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")
    with pytest.raises(ValidationError, match="STRIPE_WEBHOOK_SECRET"):
        Settings()


def test_deployment_requires_all_plan_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("STRIPE_PRICE_PRIORITY_ANNUAL", "")
    with pytest.raises(ValidationError, match="price IDs"):
        Settings()


def test_deployment_requires_portal_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("STRIPE_PORTAL_CONFIGURATION_ID", "")
    with pytest.raises(ValidationError, match="STRIPE_PORTAL_CONFIGURATION_ID"):
        Settings()


def test_production_requires_live_key(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")  # test key in production
    with pytest.raises(ValidationError, match="live key"):
        Settings()


def test_live_key_refused_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="staging")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_fake")  # live key in staging
    with pytest.raises(ValidationError, match="live Stripe secret key"):
        Settings()


def test_staging_requires_test_key(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="staging")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")  # empty is not a test key
    with pytest.raises(ValidationError, match="test key"):
        Settings()


def test_valid_deployments_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    assert Settings().billing_backend == "stripe"
    deployed_env(monkeypatch, app_env="staging")
    assert Settings().billing_backend == "stripe"
