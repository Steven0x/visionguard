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


def test_production_without_test_mode_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TEST_MODE", "0")
    settings = Settings()
    assert settings.is_production is True
