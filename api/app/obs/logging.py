"""Structured JSON logging with a scrubber that never lets secrets or sensitive data reach a log
sink (CLAUDE.md #6, #7).

The scrubber redacts, in every log line (including uvicorn/gunicorn access + error logs):
- bearer tokens and JWTs (auth material),
- email addresses (PII),
- URL paths and query strings — only ``scheme://host`` survives. This is how "URLs of ncii
  cases" are kept out of logs: a leak/candidate URL never survives as a full string, so a takedown
  target's path can't leak via a log line.

Convention (enforced by code review, documented in docs/specs/production.md): never pass file
bytes or request/response bodies to the logger.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

# Order matters: strip bearer/JWT first, then whole URLs (scheme'd, then bare host/path — the HOST
# is the sensitive part for a leak/ncii domain, e.g. a victim's name as a subdomain, so we drop it
# too, not just the path), then any remaining bare email.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
# A scheme-less host+path, e.g. leak-tube.example/videos/victim — a dotted host followed by a path.
# The trailing slash is required so bare filenames/domains in prose are left alone.
_BARE_URL_RE = re.compile(r"\b[A-Za-z0-9](?:[A-Za-z0-9.-]*\.[A-Za-z]{2,})/[^\s\"'<>]*")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Server access/error loggers whose records must also pass through the scrubber.
SERVER_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error", "gunicorn.access", "gunicorn.error")


def scrub(text: str) -> str:
    """Redact secrets / PII / sensitive URLs (host included) from a single string."""
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _JWT_RE.sub("[REDACTED_JWT]", text)
    text = _URL_RE.sub("[REDACTED_URL]", text)
    text = _BARE_URL_RE.sub("[REDACTED_URL]", text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    return text


class ScrubbingFilter(logging.Filter):
    """Rewrites each record's fully-rendered message (and any exception text) through ``scrub``."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = scrub(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001 - logging must never raise
            record.msg = "[unloggable record]"
            record.args = ()
        if record.exc_info:
            # Render + scrub now, then drop exc_info so formatters don't re-render it raw.
            record.exc_text = scrub(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class JsonFormatter(logging.Formatter):
    """Compact one-line JSON. Assumes records have already been scrubbed by ScrubbingFilter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload, default=str)


def configure_logging(settings: object | None = None) -> None:
    """Install a single stdout handler on the root logger with the scrubber, and route the
    uvicorn/gunicorn loggers through it too. Idempotent. ``settings`` is the app Settings (or None
    to read fresh); we only need ``log_level`` and ``log_json``."""
    if settings is None:
        from api.app.config import get_settings

        settings = get_settings()
    level = getattr(settings, "log_level", "INFO")
    as_json = bool(getattr(settings, "log_json", False))

    scrubber = ScrubbingFilter()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(scrubber)
    handler.setFormatter(
        JsonFormatter() if as_json else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # The server loggers install their own handlers; strip them, add the scrubber to the logger
    # itself, and let records propagate to our root handler so access lines are scrubbed too.
    for name in SERVER_LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.addFilter(scrubber)
        lg.propagate = True
