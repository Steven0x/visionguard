"""SSRF fetcher: every block path, fully offline (monkeypatched resolver + MockTransport)."""

from __future__ import annotations

import httpx
import pytest

import api.app.net.fetcher as fetcher_mod
from api.app.net.fetcher import SafeFetcher
from api.app.net.ssrf import SsrfError, is_ip_allowed, validate_url


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.0.1",
        "169.254.169.254", "100.64.0.1", "224.0.0.1", "0.0.0.0", "255.255.255.255",  # noqa: S104
        "::1", "fc00::1", "fe80::1", "fd00:ec2::254", "::ffff:127.0.0.1",
    ],
)
def test_blocked_ips(ip: str) -> None:
    assert is_ip_allowed(ip) is False


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip: str) -> None:
    assert is_ip_allowed(ip) is True


@pytest.mark.parametrize(
    "url",
    ["ftp://x/y", "file:///etc/passwd", "gopher://x", "http://x:22/", "https://x:8443/"],
)
def test_validate_url_rejects_scheme_or_port(url: str) -> None:
    with pytest.raises(SsrfError):
        validate_url(url)


def test_fetch_blocks_private_dns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    # A hostname that resolves to a private IP must be refused before connecting.
    monkeypatch.setattr(
        fetcher_mod.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 80))],
    )
    with pytest.raises(SsrfError):
        SafeFetcher().fetch("http://internal.evil.test/")


def test_fetch_blocks_redirect_to_private() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    fetcher = SafeFetcher(transport=httpx.MockTransport(handler))
    # Literal public IP → getaddrinfo returns it offline; the redirect target is loopback.
    with pytest.raises(SsrfError):
        fetcher.fetch("http://93.184.216.34/")


def test_fetch_blocks_too_many_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://8.8.8.8/next"})

    fetcher = SafeFetcher(transport=httpx.MockTransport(handler))
    with pytest.raises(SsrfError):
        fetcher.fetch("http://8.8.8.8/")


def test_fetch_blocks_disallowed_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "application/zip"}, content=b"PK")

    fetcher = SafeFetcher(transport=httpx.MockTransport(handler))
    with pytest.raises(SsrfError):
        fetcher.fetch("http://8.8.8.8/file")


def test_fetch_blocks_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.app.config import get_settings

    monkeypatch.setattr(get_settings(), "fetcher_max_bytes", 16)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"x" * 64)

    fetcher = SafeFetcher(transport=httpx.MockTransport(handler))
    with pytest.raises(SsrfError):
        fetcher.fetch("http://8.8.8.8/big.png")


def test_fetch_success_returns_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # The connection target is the pinned IP; the Host header carries the original host.
        assert request.headers["host"] == "8.8.8.8"
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"\x89PNG")

    fetcher = SafeFetcher(transport=httpx.MockTransport(handler))
    result = fetcher.fetch("http://8.8.8.8/ok.png")
    assert result.content_type == "image/png"
    assert result.content == b"\x89PNG"
