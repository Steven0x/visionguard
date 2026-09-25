"""Slice 5: per-reviewer blur preference on /me."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

Auth = Callable[..., dict[str, str]]


def test_me_exposes_review_keep_blur_default_true(
    client: TestClient, auth_header: Auth
) -> None:
    r = client.get("/me", headers=auth_header("reviewer_a"))
    assert r.status_code == 200
    assert r.json()["review_keep_blur"] is True


def test_update_review_prefs(client: TestClient, auth_header: Auth) -> None:
    hdr = auth_header("reviewer_a")
    r = client.put("/me/review-prefs", headers=hdr, json={"keep_blur": False})
    assert r.status_code == 200
    assert r.json() == {"review_keep_blur": False}
    assert client.get("/me", headers=hdr).json()["review_keep_blur"] is False
    # restore for other tests
    client.put("/me/review-prefs", headers=hdr, json={"keep_blur": True})
