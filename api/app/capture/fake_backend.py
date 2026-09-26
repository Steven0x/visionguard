"""Deterministic offline capture for tests/CI — no browser, no network."""

from __future__ import annotations

import hashlib
import io

from PIL import Image

from api.app.capture.base import CaptureResult


class FakeCapture:
    def capture(self, url: str) -> CaptureResult:
        seed = int.from_bytes(hashlib.sha256(url.encode()).digest()[:3], "big")
        color = (seed % 256, (seed >> 8) % 256, (seed >> 16) % 256)
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), color).save(buf, "PNG")
        html = f"<html><head><title>Fake capture of {url}</title></head><body>{url}</body></html>"
        mhtml = f"From: <capture>\nSubject: {url}\n\n{html}"
        return CaptureResult(
            screenshot=buf.getvalue(),
            html=html.encode(),
            mhtml=mhtml.encode(),
            final_url=url,
            http_status=200,
            page_title=f"Fake capture of {url}",
            visible_counts={},
        )
