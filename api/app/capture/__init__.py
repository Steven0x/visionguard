"""Capture backend factory + the CSAM readiness gate."""

from __future__ import annotations

from functools import lru_cache

from api.app.capture.base import CaptureBackend, CaptureError, CaptureResult, fulfill_or_abort
from api.app.config import get_settings


@lru_cache
def get_capture_backend() -> CaptureBackend:
    if get_settings().capture_backend == "fake":
        from api.app.capture.fake_backend import FakeCapture

        return FakeCapture()
    from api.app.capture.playwright_backend import PlaywrightCapture

    return PlaywrightCapture()


__all__ = [
    "CaptureBackend",
    "CaptureError",
    "CaptureResult",
    "fulfill_or_abort",
    "get_capture_backend",
]
