"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from api.app.config import get_settings
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


def create_app() -> FastAPI:
    # Instantiating settings runs the AUTH_TEST_MODE-vs-APP_ENV guard: the app refuses to
    # start if the Clerk bypass is enabled outside dev/test.
    settings = get_settings()

    app = FastAPI(title="VisionGuard API", version="0.0.0")
    # Middleware is applied outermost-last: add the catch-all FIRST (inner) and CORS SECOND
    # (outer), so a 500 produced by the catch-all still passes back out through CORS and gets
    # its headers. Reversing this order would drop CORS headers on errors.
    app.add_middleware(_CatchUnhandledErrors)
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
    return app


app = create_app()
