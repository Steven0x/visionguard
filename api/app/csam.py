"""CSAM scanning gate (CLAUDE.md #7). Every image fetched from the open web or uploaded by
staff MUST pass a ``clean`` scan from the configured scanner before ANY bytes are stored or
sealed. This is the single interface all storage choke points call.

Backends:
- ``none`` (default): no scanner wired → every scan raises → the item is blocked, nothing
  stored. This is the safe production default until a real scanner is deployed.
- ``fake`` (dev/test only, refused otherwise via config validation): returns a configurable
  result so tests can exercise clean / match / error without a real scanner.
- A real PhotoDNA / Safer backend is added later behind this same interface.
"""

from __future__ import annotations

import enum
from typing import Protocol

from api.app.config import get_settings


class ScanOutcome(enum.StrEnum):
    clean = "clean"
    match = "match"
    error = "error"


class CsamScanError(Exception):
    """A scan could not produce a definitive clean/match result (fail closed)."""


class CsamScanner(Protocol):
    def scan(self, image_bytes: bytes) -> ScanOutcome:
        """Return clean/match, or raise to signal an error (treated as fail-closed)."""
        ...


class NoneScanner:
    """Default: no scanner configured. Every scan fails closed → nothing may be stored."""

    def scan(self, image_bytes: bytes) -> ScanOutcome:
        raise CsamScanError("no CSAM scanner configured (CSAM_SCANNER_BACKEND=none)")


class FakeCsamScanner:
    """Dev/test only. Result is driven by CSAM_FAKE_RESULT (default clean)."""

    def scan(self, image_bytes: bytes) -> ScanOutcome:
        result = get_settings().csam_fake_result
        if result == "match":
            return ScanOutcome.match
        if result == "error":
            raise CsamScanError("fake scanner error")
        return ScanOutcome.clean


def get_csam_scanner() -> CsamScanner:
    # Not cached: scanners are stateless + trivial, and the backend is read fresh each call.
    if get_settings().csam_scanner_backend == "fake":
        return FakeCsamScanner()
    return NoneScanner()


def csam_scanner_configured() -> bool:
    """True if a scanner backend is wired (used to skip provider/browser work when it isn't)."""
    return get_settings().csam_scanner_backend != "none"


def scan_image(image_bytes: bytes) -> ScanOutcome:
    """Scan one image, never raising: any scanner error becomes ``error`` (fail closed).
    Callers store/seal ONLY on ``ScanOutcome.clean``."""
    try:
        return get_csam_scanner().scan(image_bytes)
    except Exception:  # noqa: BLE001 - all failures are fail-closed
        return ScanOutcome.error
