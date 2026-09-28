"""Email backends: an in-memory capture-only Outbox (dev/test) and SendGrid (prod).

The exact message that goes out is sealed by the notice service; this layer only transports it.
Header/recipient values are already CR/LF-sanitized upstream (services/notice_render), and this
layer re-checks defensively before handing anything to a transport.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from api.app.config import get_settings


class EmailSendError(Exception):
    """The transport failed or is not available."""


class EmailRateLimited(EmailSendError):
    """The per-minute send rate limit was exceeded."""


@dataclass
class EmailMessage:
    to: list[str]
    subject: str
    body: str
    from_addr: str
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class SendResult:
    ok: bool
    backend: str
    provider_message_id: str | None = None


_INJECTION = ("\r", "\n", "\x00")


def _assert_no_injection(message: EmailMessage) -> None:
    """Defense in depth: refuse a message whose headers still contain CR/LF/NUL."""
    header_values = [message.subject, message.from_addr, *(message.to)]
    if message.reply_to:
        header_values.append(message.reply_to)
    header_values.extend(message.headers.keys())
    header_values.extend(message.headers.values())
    for value in header_values:
        if any(c in value for c in _INJECTION):
            raise EmailSendError("refusing to send: header/recipient injection detected")
    if not message.to:
        raise EmailSendError("refusing to send: no recipient")


class EmailBackend(Protocol):
    name: str

    def send(self, message: EmailMessage) -> SendResult: ...


class _RateLimiter:
    """A simple in-process sliding-window limiter (per-minute)."""

    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._events: deque[float] = deque()

    def check_and_record(self) -> None:
        if self._per_minute <= 0:
            return
        now = time.monotonic()
        while self._events and now - self._events[0] >= 60.0:
            self._events.popleft()
        if len(self._events) >= self._per_minute:
            raise EmailRateLimited("email rate limit exceeded; try again shortly")
        self._events.append(now)


class OutboxBackend:
    """Captures messages in memory instead of sending. Never touches the network."""

    name = "outbox"

    def __init__(self, per_minute: int) -> None:
        self.sent: list[EmailMessage] = []
        self._limiter = _RateLimiter(per_minute)

    def send(self, message: EmailMessage) -> SendResult:
        _assert_no_injection(message)
        self._limiter.check_and_record()
        self.sent.append(message)
        return SendResult(
            ok=True, backend=self.name, provider_message_id=f"outbox-{len(self.sent)}"
        )

    def clear(self) -> None:
        self.sent.clear()


class SendGridBackend:
    """Sends via SendGrid. Production-only (config refuses it in dev/test)."""

    name = "sendgrid"

    def __init__(self, api_key: str, per_minute: int) -> None:
        self._api_key = api_key
        self._limiter = _RateLimiter(per_minute)

    def send(self, message: EmailMessage) -> SendResult:
        _assert_no_injection(message)
        self._limiter.check_and_record()
        try:  # Lazy import: the dependency is only needed on the real send path.
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
        except ImportError as exc:  # pragma: no cover - prod dependency
            raise EmailSendError(
                "sendgrid package is not installed; cannot send via the SendGrid backend"
            ) from exc
        mail = Mail(
            from_email=message.from_addr,
            to_emails=message.to,
            subject=message.subject,
            plain_text_content=message.body,
        )
        if message.reply_to:
            mail.reply_to = message.reply_to
        try:  # pragma: no cover - network path, exercised only in production
            response = SendGridAPIClient(self._api_key).send(mail)
        except Exception as exc:
            raise EmailSendError(f"SendGrid send failed: {exc}") from exc
        message_id = None
        if getattr(response, "headers", None):
            message_id = response.headers.get("X-Message-Id")
        return SendResult(ok=True, backend=self.name, provider_message_id=message_id)


@lru_cache
def get_email_backend() -> EmailBackend:
    settings = get_settings()
    if settings.email_backend == "sendgrid":
        return SendGridBackend(settings.sendgrid_api_key, settings.email_rate_limit_per_min)
    return OutboxBackend(settings.email_rate_limit_per_min)


def get_outbox() -> OutboxBackend:
    """The outbox backend (dev/test only). Raises if a non-outbox backend is configured."""
    backend = get_email_backend()
    if not isinstance(backend, OutboxBackend):
        raise RuntimeError("email backend is not the outbox")
    return backend
