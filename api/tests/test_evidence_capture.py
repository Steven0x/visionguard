"""Slice 7: the SSRF browser guard, write-once storage, sealing, verify, and the CSAM gate."""

from __future__ import annotations

import pytest

from api.app.capture.base import fulfill_or_abort
from api.app.net.fetcher import FakeFetcher
from api.app.storage.evidence import EvidenceExists, FakeEvidenceStorage


class _BlockingFetcher:
    """Stand-in whose fetch always raises SsrfError (as SafeFetcher would for a blocked IP)."""

    def fetch(self, url: str):
        from api.app.net.ssrf import SsrfError

        raise SsrfError(f"blocked: {url}")


def test_guard_fulfills_get_via_safe_fetcher() -> None:
    decision = fulfill_or_abort("GET", "https://good.example/x.png", FakeFetcher())
    assert decision.action == "fulfill" and decision.result is not None


def test_guard_aborts_non_get() -> None:
    for method in ("POST", "PUT", "OPTIONS", "CONNECT"):
        assert fulfill_or_abort(method, "https://good.example/", FakeFetcher()).action == "abort"


def test_guard_aborts_blocked_target() -> None:
    # A page embedding the cloud-metadata IP or a private-IP subresource: SafeFetcher raises,
    # the handler aborts, so the browser never loads it.
    for url in ("http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/secret.png"):
        assert fulfill_or_abort("GET", url, _BlockingFetcher()).action == "abort"


def test_guard_aborts_image_that_fails_csam(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every image the browser loads is CSAM-scanned at this egress point; a non-clean image is
    # aborted so it never enters the page/screenshot/sealed archive.
    from api.app.config import get_settings

    monkeypatch.setattr(get_settings(), "csam_fake_result", "match")
    assert fulfill_or_abort("GET", "https://good.example/x.png", FakeFetcher()).action == "abort"


def test_evidence_storage_is_write_once() -> None:
    store = FakeEvidenceStorage()
    store.seal_object("k/1/screenshot.png", b"first", "image/png")
    assert store.get_object("k/1/screenshot.png") == b"first"
    with pytest.raises(EvidenceExists):
        store.seal_object("k/1/screenshot.png", b"second", "image/png")
    assert store.get_object("k/1/screenshot.png") == b"first"  # original preserved
