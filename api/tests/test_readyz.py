"""/readyz reports dependency health, returns 503 when any dep is down, leaks no hosts, and
caches its result so it can't hammer the backends. /healthz stays a dependency-free liveness ping.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app.obs import readiness


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    readiness._reset_cache_for_tests()


def test_healthz_is_liveness_only(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readyz_ok_when_all_healthy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "_probe", lambda: {"db": True, "redis": True, "storage": True})
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"db": True, "redis": True, "storage": True}}


def test_readyz_503_when_a_dep_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(readiness, "_probe", lambda: {"db": True, "redis": False, "storage": True})
    r = client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unavailable" and body["checks"]["redis"] is False
    # No host/URL/secret in the body — only per-dependency booleans.
    assert set(body["checks"]) == {"db", "redis", "storage"}
    assert "redis://" not in r.text and "localhost" not in r.text


def test_readyz_caches_result(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _counting_probe() -> dict[str, bool]:
        calls["n"] += 1
        return {"db": True, "redis": True, "storage": True}

    monkeypatch.setattr(readiness, "_probe", _counting_probe)
    client.get("/readyz")
    client.get("/readyz")
    client.get("/readyz")
    assert calls["n"] == 1  # cached within the ~5s TTL
