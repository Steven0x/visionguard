"""The Clerk-bypass may never be enabled outside dev/test."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.app.config import Settings


def test_refuses_test_mode_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TEST_MODE", "1")
    with pytest.raises(ValidationError):
        Settings()


def test_allows_test_mode_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTH_TEST_MODE", "1")
    settings = Settings()
    assert settings.auth_test_mode is True


def test_production_refuses_to_boot_without_a_real_csam_scanner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With no real scanner connected (the shipped default), production cannot start. Intended.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TEST_MODE", "0")
    monkeypatch.setenv("CSAM_SCANNER_BACKEND", "none")
    with pytest.raises(ValidationError):
        Settings()


def test_refuses_fake_csam_scanner_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TEST_MODE", "0")
    monkeypatch.setenv("CSAM_SCANNER_BACKEND", "fake")
    with pytest.raises(ValidationError):
        Settings()
