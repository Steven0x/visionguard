"""Discovery failure/billing semantics (follow-up to the real-SerpApi walkthrough):

- SerpApi's benign "no results" 200 is NOT a failure and NOT billed (the bug that made every
  keyword_scan fail on the first empty name-sweep).
- a real provider failure records a sanitized reason on run.error and counts only billed calls.
- the dev-only Lens tunnel signs asset URLs against a public base, and only when APP_ENV=dev.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from worker import discovery as wd
from worker.discovery import keyword_scan, reverse_image_scan

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryRun, RunKind, RunStatus
from api.app.providers.base import ProviderError, ProviderResponse, ProviderResult
from api.app.providers.serpapi import SerpApiSearchProvider
from api.tests.discohelpers import authorized_subject


def _mock_serpapi(payload: dict, status: int = 200):
    def _get(url, params=None, timeout=None):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(status, json=payload))
        )
        try:
            return client.get(url, params=params)
        finally:
            client.close()

    return _get


def _latest_run(schema: str, kind: RunKind) -> DiscoveryRun:
    with tenant_session(schema) as s:
        run = s.scalar(
            select(DiscoveryRun).where(DiscoveryRun.kind == kind).order_by(DiscoveryRun.id.desc())
        )
        assert run is not None
        return run


# ── provider level ──────────────────────────────────────────────────────────


def test_serpapi_no_results_is_empty_not_billed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "api.app.providers.serpapi.httpx.get",
        _mock_serpapi({"error": "Google hasn't returned any results for this query."}),
    )
    resp = SerpApiSearchProvider("KEY", 7).search('site:instagram.com "nobody"')
    assert resp.results == []
    assert resp.calls_made == 0 and resp.cost_cents == 0  # SerpApi doesn't bill an empty result


def test_serpapi_invalid_key_raises_with_reason(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "api.app.providers.serpapi.httpx.get",
        _mock_serpapi({"error": "Invalid API key, please check your SerpApi account."}),
    )
    with pytest.raises(ProviderError) as exc:
        SerpApiSearchProvider("SECRETKEY", 1).search("q")
    message = str(exc.value)
    assert "SerpApi" in message and "Invalid API key" in message  # surfaced for the UI
    assert "SECRETKEY" not in message  # never leaks our key


# ── worker level ──────────────────────────────────────────────────────────────


def test_keyword_scan_no_results_completes_and_bills_nothing(
    db, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, handles=("@star",))

    class _Empty:
        name = "google_search"

        def search(self, query: str) -> ProviderResponse:
            return ProviderResponse(results=[], calls_made=0, cost_cents=0)  # not billed

    monkeypatch.setattr(wd, "get_keyword_provider", lambda: _Empty())
    assert keyword_scan.run(new_workspace.id, sid) == "completed"
    run = _latest_run(schema, RunKind.keyword)
    assert run.status == RunStatus.completed
    assert run.calls_made == 0 and run.estimated_cost_cents == 0 and run.error is None


def test_keyword_scan_failure_records_reason_and_bills_only_successful(
    db, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, handles=("@star",))

    class _FailAfterTwo:
        name = "google_search"
        calls = 0

        def search(self, query: str) -> ProviderResponse:
            self.calls += 1
            if self.calls > 2:
                raise ProviderError("SerpApi: Your account has run out of searches")
            return ProviderResponse(
                results=[ProviderResult(source_url=f"https://x.example/{self.calls}", kind="link")],
                calls_made=1,
                cost_cents=1,
            )

    monkeypatch.setattr(wd, "get_keyword_provider", lambda: _FailAfterTwo())
    assert keyword_scan.run(new_workspace.id, sid) == "failed"
    run = _latest_run(schema, RunKind.keyword)
    assert run.status == RunStatus.failed
    assert run.error is not None and "run out of searches" in run.error
    # Only the two billed calls count — not the reserved query count.
    assert run.calls_made == 2 and run.estimated_cost_cents == 2
    assert run.candidates_found == 2  # candidates found before the failure are kept


# ── dev Lens tunnel ─────────────────────────────────────────────────────────


def test_fake_storage_signs_against_public_base():
    from api.app.storage.fake import FakeStorage

    url = FakeStorage().generate_download_url(
        "k/obj", filename="a.png", expires_in=60, public_base_url="https://tunnel.example/"
    )
    assert url.startswith("https://tunnel.example/k/obj")


def test_dev_lens_base_only_takes_effect_in_dev(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "discovery_asset_public_base_url", "https://tunnel.example/")
    monkeypatch.setattr(s, "app_env", "dev")
    assert s.dev_lens_asset_base_url == "https://tunnel.example"
    monkeypatch.setattr(s, "app_env", "production")
    assert s.dev_lens_asset_base_url is None  # never leaks into a deployment


def test_reverse_scan_signs_asset_url_against_dev_tunnel(
    db, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    s = get_settings()
    monkeypatch.setattr(s, "app_env", "dev")
    monkeypatch.setattr(s, "discovery_asset_public_base_url", "https://tunnel.example")
    seen: dict[str, str] = {}

    class _Capture:
        name = "google_lens"

        def search(self, image_url: str) -> ProviderResponse:
            seen["url"] = image_url
            return ProviderResponse(results=[], calls_made=1, cost_cents=1)

    monkeypatch.setattr(wd, "get_reverse_image_providers", lambda **k: [_Capture()])
    sid, aid = authorized_subject(new_workspace.schema_name, ready_asset=True)
    assert reverse_image_scan.run(new_workspace.id, sid, aid) == "completed"
    assert seen["url"].startswith("https://tunnel.example/")
