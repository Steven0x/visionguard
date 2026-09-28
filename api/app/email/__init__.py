"""Outbound email for notices (Slice 8).

`get_email_backend()` returns the configured backend, mirroring `get_evidence_storage()` /
`get_csam_scanner()`. The default `outbox` backend captures messages and never touches the
network, so dev/test can never send real mail; `sendgrid` is production-only (guarded in config).
"""

from api.app.email.backend import (
    EmailBackend,
    EmailMessage,
    EmailRateLimited,
    EmailSendError,
    OutboxBackend,
    SendResult,
    get_email_backend,
    get_outbox,
)

__all__ = [
    "EmailBackend",
    "EmailMessage",
    "EmailRateLimited",
    "EmailSendError",
    "OutboxBackend",
    "SendResult",
    "get_email_backend",
    "get_outbox",
]
