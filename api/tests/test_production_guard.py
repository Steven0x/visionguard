"""The deployed-env config guard (Slice 11): a staging/production deployment refuses to boot
unless every backend is real, Clerk is configured, CORS is an exact origin list, MFA is required,
and production evidence retention is >= 7 years. See docs/specs/production.md."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.app.config import Settings, _is_exact_origin
from api.tests.deployhelpers import deployed_env


def test_valid_production_config_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    settings = Settings()
    assert settings.is_production and settings.is_deployed


def test_valid_staging_config_boots_with_outbox_email(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="staging")
    settings = Settings()
    assert settings.is_deployed and not settings.is_production
    assert settings.email_backend == "outbox"


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("EMBEDDER_BACKEND", "fake"),
        ("FETCHER_BACKEND", "fake"),
        ("PROVIDER_BACKEND", "fake"),
        ("CAPTURE_BACKEND", "fake"),
        ("TSA_BACKEND", "fake"),
        ("STORAGE_BACKEND", "fake"),
    ],
)
def test_refuses_any_fake_backend_in_deployment(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str
) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv(var, value)
    with pytest.raises(ValidationError, match=var):
        Settings()


def test_production_default_config_fails_only_on_csam(monkeypatch: pytest.MonkeyPatch) -> None:
    """A production config with every real backend still refuses to boot — because no real CSAM
    scanner is connected. That single blocker is intended (CLAUDE.md #7)."""
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("CSAM_SCANNER_BACKEND", "none")  # the shipped default
    with pytest.raises(ValidationError, match="CSAM_SCANNER_BACKEND"):
        Settings()


def test_refuses_missing_clerk_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("CLERK_JWT_ISSUER", "")
    with pytest.raises(ValidationError, match="CLERK_JWT_ISSUER"):
        Settings()


def test_refuses_missing_clerk_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("CLERK_JWKS_URL", "")
    with pytest.raises(ValidationError, match="CLERK_JWKS_URL"):
        Settings()


def test_refuses_mfa_off(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("CLERK_REQUIRE_MFA", "0")
    with pytest.raises(ValidationError, match="CLERK_REQUIRE_MFA"):
        Settings()


@pytest.mark.parametrize(
    ("var", "match"),
    [
        ("LOG_JSON", "LOG_JSON"),
        ("SECURITY_HEADERS_ENABLED", "SECURITY_HEADERS_ENABLED"),
        ("RATE_LIMIT_ENABLED", "RATE_LIMIT_ENABLED"),
    ],
)
def test_refuses_hardening_controls_off(
    monkeypatch: pytest.MonkeyPatch, var: str, match: str
) -> None:
    # A deployment must not boot degraded just because a toml env block was edited.
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv(var, "0")
    with pytest.raises(ValidationError, match=match):
        Settings()


@pytest.mark.parametrize(
    "origins",
    [
        "",
        "*",
        "https://app.example/path",
        "https://app.example/",
        "app.example",
        "https://app.example#",
        "https://app.example?x=1",
        "https://user@app.example",
    ],
)
def test_refuses_non_exact_cors(monkeypatch: pytest.MonkeyPatch, origins: str) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("ALLOWED_ORIGINS", origins)
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings()


def test_production_requires_sendgrid(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("EMAIL_BACKEND", "outbox")
    with pytest.raises(ValidationError, match="EMAIL_BACKEND"):
        Settings()


def test_staging_refuses_sendgrid(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="staging")
    monkeypatch.setenv("EMAIL_BACKEND", "sendgrid")
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake")
    with pytest.raises(ValidationError, match="EMAIL_BACKEND|sendgrid"):
        Settings()


def test_production_retention_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("EVIDENCE_RETENTION_DAYS", "365")
    with pytest.raises(ValidationError, match="EVIDENCE_RETENTION_DAYS"):
        Settings()


def test_production_retention_override_allows_shorter(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_env(monkeypatch, app_env="production")
    monkeypatch.setenv("EVIDENCE_RETENTION_DAYS", "365")
    monkeypatch.setenv("EVIDENCE_RETENTION_OVERRIDE_REASON", "counsel: 1yr pilot per DPA-42")
    assert Settings().evidence_retention_days == 365


def test_dev_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    # The default dev config (fakes everywhere) still builds fine.
    monkeypatch.setenv("APP_ENV", "dev")
    assert Settings().is_deployed is False


def test_exact_origin_helper() -> None:
    assert _is_exact_origin("https://app.example")
    assert _is_exact_origin("http://localhost:5173")
    assert not _is_exact_origin("https://app.example/")
    assert not _is_exact_origin("https://app.example/path")
    assert not _is_exact_origin("*")
    assert not _is_exact_origin("app.example")
    assert not _is_exact_origin("https://user@app.example")
    # A bare trailing fragment/query and interior control chars must be rejected too.
    assert not _is_exact_origin("https://app.example#")
    assert not _is_exact_origin("https://app.example?x=1")
    assert not _is_exact_origin("https://app.example\x00.evil.example")
    assert not _is_exact_origin("https://app.example\n")
    assert not _is_exact_origin("https://app.exαmple")  # non-ascii
