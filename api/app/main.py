"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from api.app.config import get_settings
from api.app.middleware.security import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from api.app.obs.logging import configure_logging
from api.app.obs.readiness import verify_deployed_readiness
from api.app.obs.sentry import init_sentry
from api.app.routers import (
    assets,
    cases,
    csam,
    discovery,
    evidence,
    health,
    me,
    notices,
    outcomes,
    records,
    reports,
    review,
    subjects,
    workspaces,
)

logger = logging.getLogger("visionguard")


class _CatchUnhandledErrors(BaseHTTPMiddleware):
    """Convert an unhandled exception into a 500 JSON response.

    Registered INSIDE the CORS middleware so the response still flows back out through CORS and
    carries the CORS headers — otherwise Starlette's outermost ServerErrorMiddleware renders the
    500 without them and the browser only sees an opaque "Failed to fetch" instead of the error.
    HTTPException/validation errors are already handled inside CORS, so they're unaffected.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("unhandled error handling %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "internal server error"})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: scrubbed logging, error tracking, and (deployments only) a readiness gate that
    verifies evidence object lock + session advisory-lock support. Migrations are NEVER run here —
    they run as a separate release step (see docs/ops/deploy.md)."""
    settings = get_settings()
    configure_logging(settings)
    init_sentry(settings)
    verify_deployed_readiness(settings)  # no-op outside staging/production
    yield


def create_app() -> FastAPI:
    # Instantiating settings runs the config guards: the app refuses to start if the Clerk bypass
    # is enabled outside dev/test, or if a deployment isn't fully production-safe.
    settings = get_settings()

    app = FastAPI(title="VisionGuard API", version="0.0.0", lifespan=lifespan)
    # Middleware is applied outermost-last. Add inner→outer: catch-all (innermost) so a 500 still
    # flows back out through the layers above it; then security headers + the request-size limit;
    # then CORS (outermost) so even a 413/500 carries CORS headers for the browser.
    app.add_middleware(_CatchUnhandledErrors)
    if settings.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(workspaces.router)
    app.include_router(subjects.router)
    app.include_router(records.router)
    app.include_router(assets.router)
    app.include_router(discovery.router)
    app.include_router(review.router)
    app.include_router(cases.router)
    app.include_router(evidence.router)
    app.include_router(csam.router)
    app.include_router(notices.router)
    app.include_router(notices.admin_router)
    app.include_router(outcomes.router)
    app.include_router(reports.router)
    return app


app = create_app()
