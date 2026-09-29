"""Health endpoints — the only unauthenticated routes.

- ``/healthz`` is liveness: the process is up (no dependency checks). Used by the platform to
  decide whether to restart the machine.
- ``/readyz`` is readiness: DB, Redis and storage are reachable. Used to decide whether to route
  traffic. The result is cached ~5s so the probe can't be turned into a DoS on the backends.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.app.obs.readiness import check_readiness

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> JSONResponse:
    checks = check_readiness()
    ok = all(checks.values())
    # No hosts/URLs/secrets in the body — just per-dependency booleans.
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "unavailable", "checks": checks},
    )
