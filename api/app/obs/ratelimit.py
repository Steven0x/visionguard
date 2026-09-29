"""Fixed-window rate limiting for authenticated write endpoints.

Keyed on the VERIFIED identity — the resolved ``staff.id`` for an authenticated request, or the
client IP (taken ONLY from Fly's ``Fly-Client-IP`` header, never the spoofable
``X-Forwarded-For``) for a request whose token failed verification. A forged token therefore can
neither reset nor consume another staff member's quota: it never reaches the staff-keyed path.

Off unless ``RATE_LIMIT_ENABLED`` (so dev/test are unaffected); deployments turn it on.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from fastapi import Request

from api.app.config import get_settings

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


@lru_cache
def _redis() -> Any:
    import redis

    return redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)


def client_ip(request: Request) -> str:
    """Trust only Fly's edge-set header; ignore X-Forwarded-For (client-spoofable)."""
    return request.headers.get("fly-client-ip") or "unknown"


def enforce_write_rate_limit(request: Request, *, identity: str) -> None:
    """Count one mutating request for ``identity`` in the current minute; raise if over the limit.

    Non-mutating methods and the disabled flag are no-ops. Redis errors fail OPEN (availability
    over strictness) — the limiter must never take down the API on a Redis blip.
    """
    settings = get_settings()
    if not settings.rate_limit_enabled or request.method not in _MUTATING_METHODS:
        return
    now = time.time()
    window = int(now // 60)
    key = f"vg:rl:{identity}:{window}"
    try:
        client = _redis()
        count = client.incr(key)
        if count == 1:
            client.expire(key, 60)
    except Exception:  # noqa: BLE001 - fail open on Redis trouble
        return
    if count > settings.rate_limit_writes_per_min:
        raise RateLimited(retry_after=60 - int(now % 60))
