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


def capture_csam_ready() -> bool:
    """Fail closed (CLAUDE.md #7): capturing/sealing open-web imagery is only allowed once a
    CSAM scanner is configured. The fake backend (tests/CI) is exempt.

    PRE-PRODUCTION BLOCKER: ``csam_scanner_enabled`` must NOT be turned on until a real
    PhotoDNA-style scanner is wired into the seal path (positive → NCMEC path, never stored).
    Setting the flag today merely lifts this gate without a scan — the scanner body is the
    tracked pre-production requirement (see docs/BACKLOG.md, docs/adr/0009-evidence-capture.md).
    This is the second such choke point, alongside Slice 4's ``add_image_candidate``."""
    settings = get_settings()
    return settings.capture_backend == "fake" or settings.csam_scanner_enabled


__all__ = [
    "CaptureBackend",
    "CaptureError",
    "CaptureResult",
    "capture_csam_ready",
    "fulfill_or_abort",
    "get_capture_backend",
]
