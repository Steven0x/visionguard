"""Email backend + config: dev/test can never send real mail; the outbox captures; header/
recipient injection is refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.app.config import Settings
from api.app.email.backend import (
    EmailMessage,
    EmailRateLimited,
    EmailSendError,
    OutboxBackend,
)
from api.tests.deployhelpers import deployed_env


def _msg(
    *,
    to: list[str] | None = None,
    subject: str = "Takedown",
    body: str = "body",
    from_addr: str = "notices@visionguard.example",
) -> EmailMessage:
    return EmailMessage(
        to=["abuse@host.invalid"] if to is None else to,
        subject=subject, body=body, from_addr=from_addr,
    )


def test_outbox_captures_and_never_sends() -> None:
    backend = OutboxBackend(per_minute=100)
    result = backend.send(_msg())
    assert result.ok and result.backend == "outbox"
    assert len(backend.sent) == 1 and backend.sent[0].subject == "Takedown"


def test_outbox_refuses_header_injection() -> None:
    backend = OutboxBackend(per_minute=100)
    with pytest.raises(EmailSendError):
        backend.send(_msg(subject="Takedown\r\nBcc: victim@evil.invalid"))
    with pytest.raises(EmailSendError):
        backend.send(_msg(to=["abuse@host.invalid\nBcc: x@evil.invalid"]))
    assert backend.sent == []


def test_outbox_refuses_no_recipient() -> None:
    backend = OutboxBackend(per_minute=100)
    with pytest.raises(EmailSendError):
        backend.send(_msg(to=[]))


def test_outbox_rate_limit() -> None:
    backend = OutboxBackend(per_minute=2)
    backend.send(_msg())
    backend.send(_msg())
    with pytest.raises(EmailRateLimited):
        backend.send(_msg())


def test_config_refuses_sendgrid_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EMAIL_BACKEND", "sendgrid")
    with pytest.raises(ValidationError):
        Settings()


def test_config_sendgrid_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TEST_MODE", "0")
    monkeypatch.setenv("CSAM_SCANNER_BACKEND", "none")
    monkeypatch.setenv("EMAIL_BACKEND", "sendgrid")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_config_sendgrid_ok_in_production_with_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A fully production-safe config (real scanner registered on the test side) boots and sends
    # via SendGrid.
    deployed_env(monkeypatch, app_env="production")
    settings = Settings()
    assert settings.email_backend == "sendgrid"
