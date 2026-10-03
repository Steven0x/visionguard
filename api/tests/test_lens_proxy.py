"""The dev-only Lens tunnel proxy (api/app/dev/lens_proxy.py).

Covers the allowlist decision for every rejection the tunnel must enforce, and the start-up
guards (dev-only + non-default MinIO creds). Pure functions — no server or network.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.config import get_settings
from api.app.dev.lens_proxy import assert_safe_to_run, authorize

BUCKET = "vg-assets"


def _presign(*, expires: int = 300, signed_minutes_ago: int = 0, signature: str = "abc123") -> str:
    signed = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=signed_minutes_ago)
    date = signed.strftime("%Y%m%dT%H%M%SZ")
    parts = [
        "X-Amz-Algorithm=AWS4-HMAC-SHA256",
        "X-Amz-Credential=KEY%2F20261003%2Fus-east-1%2Fs3%2Faws4_request",
        f"X-Amz-Date={date}",
        f"X-Amz-Expires={expires}",
        "X-Amz-SignedHeaders=host",
    ]
    if signature is not None:
        parts.append(f"X-Amz-Signature={signature}")
    return "&".join(parts)


def test_allows_presigned_object_get():
    d = authorize("GET", f"/{BUCKET}/ws_x/thumb/abc.png", _presign(), bucket=BUCKET)
    assert d.allowed and d.status == 200


def test_allows_head():
    d = authorize("HEAD", f"/{BUCKET}/ws_x/a.png", _presign(), bucket=BUCKET)
    assert d.allowed


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_rejects_non_get_methods(method: str):
    d = authorize(method, f"/{BUCKET}/ws_x/a.png", _presign(), bucket=BUCKET)
    assert not d.allowed and d.status == 405


def test_rejects_other_bucket_including_evidence():
    d = authorize("GET", "/vg-evidence/case/1/manifest.json", _presign(), bucket=BUCKET)
    assert not d.allowed and d.status == 403


@pytest.mark.parametrize("path", [f"/{BUCKET}", f"/{BUCKET}/", "/"])
def test_rejects_bucket_listing_and_root(path: str):
    d = authorize("GET", path, _presign(), bucket=BUCKET)
    assert not d.allowed and d.status == 403


def test_rejects_listing_query_even_with_key():
    d = authorize("GET", f"/{BUCKET}/x", "list-type=2&" + _presign(), bucket=BUCKET)
    assert not d.allowed and d.status == 403


def test_rejects_object_subresource_ops():
    for op in ("acl", "tagging", "uploads", "retention", "legal-hold"):
        d = authorize("GET", f"/{BUCKET}/x", f"{op}&" + _presign(), bucket=BUCKET)
        assert not d.allowed and d.status == 403, op


@pytest.mark.parametrize("path", ["/minio/health/live", "/console", "/"])
def test_rejects_console_and_non_bucket_paths(path: str):
    d = authorize("GET", path, _presign(), bucket=BUCKET)
    assert not d.allowed and d.status == 403


def test_rejects_unsigned_request():
    # No query at all.
    assert not authorize("GET", f"/{BUCKET}/x", "", bucket=BUCKET).allowed
    # Has X-Amz-Date/Expires but no X-Amz-Signature.
    unsigned = _presign(signature=None)
    d = authorize("GET", f"/{BUCKET}/x", unsigned, bucket=BUCKET)
    assert not d.allowed and d.status == 403 and "unsigned" in d.reason


def test_rejects_expired_presign():
    expired = _presign(expires=300, signed_minutes_ago=20)  # signed 20m ago, 5m TTL
    d = authorize("GET", f"/{BUCKET}/x", expired, bucket=BUCKET)
    assert not d.allowed and d.status == 403 and "expired" in d.reason


def test_rejects_malformed_expiry():
    q = "X-Amz-Signature=abc&X-Amz-Date=not-a-date&X-Amz-Expires=300"
    d = authorize("GET", f"/{BUCKET}/x", q, bucket=BUCKET)
    assert not d.allowed and d.status == 403


# ── start-up guards ───────────────────────────────────────────────────────────


def test_assert_safe_runs_in_dev_with_nondefault_creds(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "app_env", "dev")
    monkeypatch.setattr(s, "storage_access_key_id", "vg-dev-key")
    monkeypatch.setattr(s, "storage_secret_access_key", "vg-dev-secret")
    assert_safe_to_run(s)  # no raise


def test_assert_safe_refuses_outside_dev(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "app_env", "production")
    monkeypatch.setattr(s, "storage_access_key_id", "vg-dev-key")
    monkeypatch.setattr(s, "storage_secret_access_key", "vg-dev-secret")
    with pytest.raises(RuntimeError, match="dev-only"):
        assert_safe_to_run(s)


def test_assert_safe_refuses_default_minio_creds(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "app_env", "dev")
    monkeypatch.setattr(s, "storage_access_key_id", "minioadmin")
    monkeypatch.setattr(s, "storage_secret_access_key", "minioadmin")
    with pytest.raises(RuntimeError, match="default credentials"):
        assert_safe_to_run(s)
