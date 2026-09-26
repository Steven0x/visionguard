"""Real evidence capture via Playwright/Chromium. Lazy-imports playwright (the `capture` extra).

Hardening (docs/specs/evidence.md): a fresh context per capture with no cookies/storage, no
downloads, service workers blocked, WebRTC + WebSockets neutralised (no local-network probing /
IP leak), and a context.route handler that fetches every GET through the SSRF-safe SafeFetcher
(pinned IP) and fulfills — the browser never opens its own socket to a target — aborting
non-GET and blocked targets.
"""

from __future__ import annotations

import re
from typing import Any

from api.app.capture.base import CaptureResult, fulfill_or_abort
from api.app.config import get_settings

# Kill WebSocket + WebRTC in-page so nothing can bypass the route handler's HTTP egress.
_NEUTRALISE_JS = """
() => {
  try { delete window.WebSocket; } catch (e) {}
  try { window.WebSocket = undefined; } catch (e) {}
  for (const k of ['RTCPeerConnection','webkitRTCPeerConnection','RTCDataChannel']) {
    try { window[k] = undefined; } catch (e) {}
  }
  try { navigator.mediaDevices = undefined; } catch (e) {}
}
"""

_LAUNCH_ARGS = [
    "--disable-webrtc",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--no-sandbox",
]

_COUNT_PATTERNS = {
    "followers": re.compile(r"([\d,.]+)\s+followers", re.I),
    "likes": re.compile(r"([\d,.]+)\s+likes", re.I),
    "views": re.compile(r"([\d,.]+)\s+views", re.I),
}
_PRICE = re.compile(r"[$£€]\s?[\d,]+(?:\.\d{2})?")


def _parse_counts(text: str) -> dict:
    out: dict[str, str] = {}
    for name, pattern in _COUNT_PATTERNS.items():
        m = pattern.search(text)
        if m:
            out[name] = m.group(1)
    price = _PRICE.search(text)
    if price:
        out["price"] = price.group(0)
    return out


class PlaywrightCapture:
    def capture(self, url: str) -> CaptureResult:  # pragma: no cover - needs a real browser
        from playwright.sync_api import sync_playwright

        settings = get_settings()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                accept_downloads=False,
                service_workers="block",
            )
            context.add_init_script(_NEUTRALISE_JS)

            def _handle(route: Any, request: Any) -> None:
                decision = fulfill_or_abort(request.method, request.url)
                if decision.action == "fulfill" and decision.result is not None:
                    route.fulfill(
                        status=200,
                        content_type=decision.result.content_type,
                        body=decision.result.content,
                    )
                else:
                    route.abort()

            context.route("**/*", _handle)
            page = context.new_page()

            load_error = None
            status = None
            try:
                resp = page.goto(
                    url, wait_until="networkidle", timeout=settings.capture_nav_timeout_ms
                )
                status = resp.status if resp else None
            except Exception as exc:  # noqa: BLE001 - record, keep the partial capture
                load_error = f"{type(exc).__name__}: {exc}"
            page.wait_for_timeout(2000)

            height = min(
                settings.capture_max_page_px,
                int(page.evaluate("document.body ? document.body.scrollHeight : 900") or 900),
            )
            page.set_viewport_size({"width": 1440, "height": min(height, 4000)})
            screenshot = page.screenshot(
                full_page=True, clip={"x": 0, "y": 0, "width": 1440, "height": height}
            )
            html = page.content().encode("utf-8")
            try:
                cdp = context.new_cdp_session(page)
                mhtml = cdp.send("Page.captureSnapshot", {"format": "mhtml"})["data"].encode()
            except Exception as exc:  # noqa: BLE001
                mhtml = f"MHTML capture failed: {exc}".encode()
            title = page.title()
            counts = _parse_counts(page.inner_text("body") if page.query_selector("body") else "")
            final_url = page.url
            browser.close()

        return CaptureResult(
            screenshot=screenshot,
            html=html,
            mhtml=mhtml,
            final_url=final_url,
            http_status=status,
            page_title=title,
            visible_counts=counts,
            load_error=load_error,
        )
