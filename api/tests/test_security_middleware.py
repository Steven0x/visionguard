"""Security headers, the received-bytes request size limit, and rate limiting keyed on the
verified staff id (a forged token can't consume another staff member's quota)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from api.app.config import get_settings
from api.app.middleware.security import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from api.app.obs import ratelimit


# ── Security headers ──────────────────────────────────────────────────────────
def _headers_app(hsts: bool) -> TestClient:
    async def ok(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", ok)])
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)
    return TestClient(app)


def test_security_headers_present() -> None:
    r = _headers_app(hsts=False).get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_added_when_enabled() -> None:
    r = _headers_app(hsts=True).get("/")
    assert "max-age=31536000" in r.headers["Strict-Transport-Security"]


# ── Request size limit (enforced on bytes actually received) ────────────────────
def _size_app(max_bytes: int) -> TestClient:
    async def echo(request: Request) -> PlainTextResponse:
        body = await request.body()
        return PlainTextResponse(f"read {len(body)}")

    app = Starlette(routes=[Route("/", echo, methods=["POST"])])
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)
    return TestClient(app)


def test_under_limit_ok() -> None:
    r = _size_app(1000).post("/", content=b"x" * 100)
    assert r.status_code == 200 and r.text == "read 100"


def test_declared_content_length_over_limit_413() -> None:
    r = _size_app(50).post("/", content=b"x" * 200)
    assert r.status_code == 413


def test_chunked_body_over_limit_413() -> None:
    # A generator body makes httpx use chunked transfer encoding (no Content-Length header), so
    # the limit must be enforced on the bytes actually streamed in.
    def chunks() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * 100  # 1000 bytes total, limit is 50

    r = _size_app(50).post("/", content=chunks())
    assert r.status_code == 413


# ── Rate limiting keyed on the verified staff id ────────────────────────────────
class _FakeRedis:
    """Minimal Redis for the fixed-window counter."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, seconds: int) -> None:
        pass


@pytest.fixture
def rate_limited(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(ratelimit, "_redis", lambda: fake)
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_writes_per_min", 2)
    return fake


def test_write_over_limit_429_with_retry_after(
    client: TestClient, new_workspace: object, auth_header, rate_limited: _FakeRedis
) -> None:
    hdr = auth_header("admin_user")
    # A cheap authenticated write: create a subject. First two pass, the third is limited.
    ws_id = new_workspace.id  # type: ignore[attr-defined]
    url = f"/workspaces/{ws_id}/subjects"
    body = {"legal_name": "Test Person", "residence_state": "CA"}
    codes = [client.post(url, headers=hdr, json=body).status_code for _ in range(3)]
    assert codes[2] == 429
    # Retry-After present on the limited response.
    limited = client.post(url, headers=hdr, json=body)
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_forged_token_does_not_reset_staff_quota(
    client: TestClient, new_workspace: object, auth_header, rate_limited: _FakeRedis
) -> None:
    hdr = auth_header("admin_user")
    ws_id = new_workspace.id  # type: ignore[attr-defined]
    url = f"/workspaces/{ws_id}/subjects"
    body = {"legal_name": "P", "residence_state": "CA"}
    client.post(url, headers=hdr, json=body)
    client.post(url, headers=hdr, json=body)
    assert client.post(url, headers=hdr, json=body).status_code == 429

    # A forged token with a brand-new subject is rejected at verification (keyed on IP), and the
    # real staff member is still limited — the forgery neither reset nor borrowed their quota.
    forged = {"Authorization": "Bearer not.a.real.token"}
    assert client.post(url, headers=forged, json=body).status_code == 401
    assert client.post(url, headers=hdr, json=body).status_code == 429
    # Only the IP key advanced from the forged attempt; the staff key stayed at its limit.
    assert any(k.startswith("vg:rl:ip:") for k in rate_limited.store)
