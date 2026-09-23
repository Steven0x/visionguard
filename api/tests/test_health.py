from fastapi.testclient import TestClient

from api.app.main import app


def test_healthz_is_open() -> None:
    # The only unauthenticated route.
    with TestClient(app) as client:
        res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
