"""A per-job Redis lock so a scheduled (beat) task runs at most once at a time.

Beat is pinned to a single machine (``fly scale count 1``; see deploy/fly/beat.toml). This lock is
belt-and-braces: if a second beat ever runs — a bad deploy, a manual start, an overlapping slow
run — the duplicate job is a no-op instead of double-dispatching scans or double-advancing cases.

Fails OPEN: if Redis is unreachable the job still runs (a missed daily job is worse than the tiny
risk of a double run while Redis is down, and the single-beat invariant already covers it). This
also means eager tests without Redis simply execute the task body.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache, wraps
from typing import Any

from api.app.config import get_settings

logger = logging.getLogger("visionguard.beat")

_DEFAULT_TTL_SECONDS = 3600


@lru_cache
def _redis() -> Any:
    import redis

    return redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)


@contextmanager
def beat_lock(name: str, *, ttl: int = _DEFAULT_TTL_SECONDS) -> Iterator[bool]:
    """Yield True if this caller holds the lock for ``name`` (and should run), else False."""
    key = f"vg:beatlock:{name}"
    token = uuid.uuid4().hex
    try:
        acquired = bool(_redis().set(key, token, nx=True, ex=ttl))
    except Exception:  # noqa: BLE001 - fail open when Redis is unreachable
        yield True
        return
    if not acquired:
        yield False
        return
    try:
        yield True
    finally:
        _release(key, token)


def _release(key: str, token: str) -> None:
    """Best-effort release; the TTL expires the lock anyway if this fails."""
    try:
        client = _redis()
        if client.get(key) in (token, token.encode()):
            client.delete(key)
    except Exception as exc:  # noqa: BLE001 - never let a release error escape a task
        logger.debug("beat lock release failed for %s: %s", key, exc)


def single_run(
    name: str, *, ttl: int = _DEFAULT_TTL_SECONDS
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a beat task to run only when it can acquire the lock; a skipped run returns None."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with beat_lock(name, ttl=ttl) as acquired:
                if not acquired:
                    logger.info("beat task %r skipped: lock held by another runner", name)
                    return None
                return fn(*args, **kwargs)

        return wrapper

    return decorator
