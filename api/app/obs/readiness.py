"""Readiness: a boot-time verification for deployments, and a cached probe for ``/readyz``.

- ``verify_deployed_readiness`` runs once at startup in staging/production and RAISES (aborting
  boot) if the evidence bucket's object lock can't be verified, or if the DB connection can't hold
  a session-level advisory lock (which a Supabase *transaction* pooler cannot — that would silently
  break tenant provisioning and the concurrent-run lock). It never runs migrations.
- ``check_readiness`` is the ``/readyz`` probe: DB + Redis + storage reachable, cached ~5s so the
  endpoint can't be used to hammer the backends.
"""

from __future__ import annotations

import time

from sqlalchemy import text

from api.app.config import Settings, get_settings
from api.app.db.session import get_engine

_READY_CACHE_TTL_SECONDS = 5.0
_ADVISORY_LOCK_PROBE_KEY = 0x5651_5245_4144_59  # "VGREADY"

# (monotonic_expiry, result) — module-level so it is shared across requests in the process.
_cache: tuple[float, dict[str, bool]] | None = None


def supports_session_advisory_lock() -> bool:
    """Take then release a session advisory lock on one connection. On a transaction pooler the
    two statements may hit different backends, so the unlock returns false — catching the misconfig.
    """
    engine = get_engine()
    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_PROBE_KEY,))
        cur.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_PROBE_KEY,))
        row = cur.fetchone()
        cur.close()
        return bool(row and row[0])
    finally:
        conn.close()


def verify_deployed_readiness(settings: Settings | None = None) -> None:
    """Raise RuntimeError if a deployment isn't safe to serve. No-op outside staging/production."""
    settings = settings or get_settings()
    if not settings.is_deployed:
        return

    from api.app.storage.evidence import get_evidence_storage

    if not get_evidence_storage().verify_object_lock():
        raise RuntimeError(
            "evidence bucket object lock could not be verified — refusing to start "
            "(evidence must be write-once; CLAUDE.md #6)."
        )
    if not supports_session_advisory_lock():
        raise RuntimeError(
            "the database connection does not support session-level advisory locks — check "
            "DATABASE_URL uses the Supabase session pooler or a direct connection, NOT the "
            "transaction pooler (see docs/ops/deploy.md)."
        )


def _probe() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    # DB
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception:  # noqa: BLE001 - probe: any failure = not ready
        checks["db"] = False
    # Redis
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        checks["redis"] = bool(client.ping())
    except Exception:  # noqa: BLE001
        checks["redis"] = False
    # Storage (assets + evidence buckets)
    try:
        from api.app.storage import get_storage
        from api.app.storage.evidence import get_evidence_storage

        checks["storage"] = get_storage().bucket_reachable() and (
            get_evidence_storage().bucket_reachable()
        )
    except Exception:  # noqa: BLE001
        checks["storage"] = False
    return checks


def check_readiness(*, use_cache: bool = True) -> dict[str, bool]:
    """Return {check: ok} for DB/Redis/storage, cached ~5s to protect the backends."""
    global _cache
    now = time.monotonic()
    if use_cache and _cache is not None and _cache[0] > now:
        return _cache[1]
    result = _probe()
    _cache = (now + _READY_CACHE_TTL_SECONDS, result)
    return result


def _reset_cache_for_tests() -> None:
    global _cache
    _cache = None
