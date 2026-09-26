"""Capture backend interface + the SSRF browser-request guard.

The guard closes the DNS-rebinding hole: instead of validating a URL and letting the browser
re-resolve + connect itself, GET requests are fetched through the Slice 4 SafeFetcher (pinned
IP, per-hop re-validation, size cap) and fulfilled; everything else is aborted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from api.app.net.fetcher import Fetcher, FetchResult, get_fetcher
from api.app.net.ssrf import SsrfError


@dataclass
class CaptureResult:
    screenshot: bytes  # PNG
    html: bytes
    mhtml: bytes
    final_url: str
    http_status: int | None
    page_title: str
    visible_counts: dict
    load_error: str | None = None


class CaptureError(Exception):
    """Raised when a capture cannot be produced (real backend only)."""


class CaptureBackend(Protocol):
    def capture(self, url: str) -> CaptureResult: ...


@dataclass
class RouteDecision:
    action: str  # "fulfill" | "abort"
    result: FetchResult | None = None
    reason: str | None = None


def fulfill_or_abort(method: str, url: str, fetcher: Fetcher | None = None) -> RouteDecision:
    """Decide how the browser route handler should treat one request. Non-GET → abort; GET →
    fetch via the SafeFetcher (SSRF-safe) and fulfill, or abort if the target is blocked.

    Pure and unit-testable (pass the fake fetcher); the real handler wires this into
    ``context.route`` and calls ``route.fulfill``/``route.abort`` accordingly."""
    if method.upper() != "GET":
        return RouteDecision(action="abort", reason=f"non-GET blocked: {method}")
    fetcher = fetcher or get_fetcher()
    try:
        result = fetcher.fetch(url)
    except SsrfError as exc:
        return RouteDecision(action="abort", reason=str(exc))
    return RouteDecision(action="fulfill", result=result)
