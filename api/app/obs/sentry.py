"""Error tracking via Sentry, behind the ``SENTRY_DSN`` flag.

No-op unless a DSN is configured, and the SDK is lazy-imported so CI/dev don't need the ``[obs]``
extra. A ``before_send`` hook runs the same scrubber as our logs over the event's message, the
request URL, and headers, so no tokens / emails / ncii URLs / file contents leave the process.
"""

from __future__ import annotations

from typing import Any

from api.app.obs.logging import scrub

_initialized = False


def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub every string in the event before it is sent to Sentry."""

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            return scrub(value)
        if isinstance(value, dict):
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        return value

    return _walk(event)


def init_sentry(settings: object | None = None) -> bool:
    """Initialise Sentry if a DSN is set. Returns True if enabled. Safe to call more than once."""
    global _initialized
    if _initialized:
        return True
    if settings is None:
        from api.app.config import get_settings

        settings = get_settings()
    dsn = getattr(settings, "sentry_dsn", "")
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except Exception:  # noqa: BLE001 - the [obs] extra may not be installed; degrade to no-op
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=getattr(settings, "app_env", "unknown"),
        integrations=[FastApiIntegration(), CeleryIntegration()],
        traces_sample_rate=float(getattr(settings, "sentry_traces_sample_rate", 0.0)),
        send_default_pii=False,
        before_send=_scrub_event,
    )
    _initialized = True
    return True
