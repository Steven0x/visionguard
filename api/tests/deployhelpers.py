"""Helpers for building a valid deployed (staging/production) Settings in tests.

A real deployment refuses to boot unless every backend is real, Clerk is configured, CORS is an
exact origin list, MFA is required, and (production) evidence retention is >= 7 years. Crucially,
it also requires a REAL CSAM scanner, and none exists yet — so a deployment cannot boot in the
product at all. To exercise the OTHER guards in isolation, tests register a fake "real" scanner
name in ``config._REAL_CSAM_BACKENDS`` (a test-side manipulation of the allowed set — NOT a
production flag or env var; nothing in shipped config can relax the CSAM requirement).
"""

from __future__ import annotations

import pytest

from api.app import config

# A sentinel real-scanner name only tests know about.
TEST_CSAM_BACKEND = "test-real-scanner"


def deployed_env(monkeypatch: pytest.MonkeyPatch, *, app_env: str = "production") -> None:
    """Set env + register a test real-CSAM backend so ``Settings()`` builds a valid deployment.

    Callers then flip a single var to assert a specific guard fires.
    """
    monkeypatch.setattr(config, "_REAL_CSAM_BACKENDS", {TEST_CSAM_BACKEND})
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("AUTH_TEST_MODE", "0")
    monkeypatch.setenv("CSAM_SCANNER_BACKEND", TEST_CSAM_BACKEND)
    monkeypatch.setenv("CLERK_JWT_ISSUER", "https://clerk.example.com")
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example.com/.well-known/jwks.json")
    monkeypatch.setenv("CLERK_REQUIRE_MFA", "1")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.visionguard.example")
    # Hardening controls the deployed-env guard requires on.
    monkeypatch.setenv("LOG_JSON", "1")
    monkeypatch.setenv("SECURITY_HEADERS_ENABLED", "1")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    # conftest pre-sets fake backends in os.environ for hermetic tests; a deployment requires the
    # real ones, so set them explicitly here (overriding the conftest fakes for this test).
    monkeypatch.setenv("EMBEDDER_BACKEND", "clip")
    monkeypatch.setenv("FETCHER_BACKEND", "safe")
    monkeypatch.setenv("PROVIDER_BACKEND", "serpapi")
    monkeypatch.setenv("CAPTURE_BACKEND", "playwright")
    monkeypatch.setenv("TSA_BACKEND", "rfc3161")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    if app_env == "production":
        monkeypatch.setenv("EMAIL_BACKEND", "sendgrid")
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake")
        monkeypatch.setenv("EMAIL_FROM", "notices@visionguard.example")
        monkeypatch.setenv("EVIDENCE_RETENTION_DAYS", "2555")
    else:  # staging: fake email only
        monkeypatch.setenv("EMAIL_BACKEND", "outbox")
