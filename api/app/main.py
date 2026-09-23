"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.config import get_settings
from api.app.routers import health, me, workspaces


def create_app() -> FastAPI:
    # Instantiating settings runs the AUTH_TEST_MODE-vs-APP_ENV guard: the app refuses to
    # start if the Clerk bypass is enabled outside dev/test.
    settings = get_settings()

    app = FastAPI(title="VisionGuard API", version="0.0.0")
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
    return app


app = create_app()
