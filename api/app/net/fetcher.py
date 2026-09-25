"""The one safe egress point for fetching found pages/images (SSRF-hardened)."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from api.app.config import get_settings
from api.app.net.ssrf import SsrfError, require_allowed_ip, validate_url

_ALLOWED_CONTENT_PREFIXES = ("image/", "text/html")


@dataclass
class FetchResult:
    final_url: str
    content_type: str
    content: bytes


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResult:
        ...


def _resolve_pinned_ip(host: str, port: int) -> str:
    """Resolve DNS once, validate every answer, and return one pinned IP to connect to."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfError(f"dns resolution failed: {host}") from exc
    if not infos:
        raise SsrfError(f"no address for host: {host}")
    for info in infos:
        require_allowed_ip(str(info[4][0]))  # any blocked answer fails the whole fetch
    return str(infos[0][4][0])


class SafeFetcher:
    """Connects to the pinned resolved IP (no rebind), re-validating each redirect hop."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def fetch(self, url: str) -> FetchResult:
        settings = get_settings()
        client = httpx.Client(
            transport=self._transport,
            follow_redirects=False,
            timeout=settings.fetcher_timeout_seconds,
            headers={"User-Agent": settings.fetcher_user_agent},
            trust_env=False,  # ignore env proxies/netrc; forward no credentials
        )
        try:
            current = url
            for _ in range(settings.fetcher_max_redirects + 1):
                scheme, host, port = validate_url(current)
                ip = _resolve_pinned_ip(host, port)
                parts = urlsplit(current)
                netloc = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
                pinned = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))

                with client.stream(
                    "GET",
                    pinned,
                    headers={"Host": host},
                    extensions={"sni_hostname": host},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SsrfError("redirect without a location")
                        current = str(httpx.URL(current).join(location))
                        continue
                    content_type = (
                        response.headers.get("content-type", "").split(";")[0].strip().lower()
                    )
                    if not any(content_type.startswith(p) for p in _ALLOWED_CONTENT_PREFIXES):
                        raise SsrfError(f"content-type not allowed: {content_type or '(none)'}")
                    buffer = bytearray()
                    for chunk in response.iter_bytes():
                        buffer += chunk
                        if len(buffer) > settings.fetcher_max_bytes:
                            raise SsrfError("response exceeds size cap")
                    return FetchResult(
                        final_url=current, content_type=content_type, content=bytes(buffer)
                    )
            raise SsrfError("too many redirects")
        finally:
            client.close()


class FakeFetcher:
    """Offline fetcher for tests: returns a deterministic tiny PNG per URL."""

    def fetch(self, url: str) -> FetchResult:
        import hashlib
        import io

        from PIL import Image

        seed = int.from_bytes(hashlib.sha256(url.encode()).digest()[:3], "big")
        color = (seed % 256, (seed >> 8) % 256, (seed >> 16) % 256)
        image = Image.new("RGB", (8, 8), color)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return FetchResult(final_url=url, content_type="image/png", content=buffer.getvalue())


@lru_cache
def get_fetcher() -> Fetcher:
    if get_settings().fetcher_backend == "fake":
        return FakeFetcher()
    return SafeFetcher()
