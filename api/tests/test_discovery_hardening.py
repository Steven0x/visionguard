"""Slice 4 review hardening: CSAM gate, secret redaction, page_url safety, settings bounds."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from worker.discovery import reverse_image_scan

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryRun, DiscoverySettings, RunStatus
from api.app.net.fetcher import FakeFetcher
from api.app.providers.base import ProviderError
from api.app.providers.serpapi import SerpApiLensProvider
from api.app.services import discovery as svc
from api.tests.discohelpers import authorized_subject


def test_add_image_candidate_refuses_without_csam_scanner(
    db, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(get_settings(), "fetcher_backend", "safe")
    monkeypatch.setattr(get_settings(), "csam_scanner_enabled", False)
    sid, _ = authorized_subject(new_workspace.schema_name)
    with tenant_session(new_workspace.schema_name) as s, pytest.raises(svc.CsamScannerRequired):
        svc.add_image_candidate(
            s, schema=new_workspace.schema_name, subject_id=sid, run_id=1,
            provider="x", query=None, source_url="https://found.example/a.png",
            page_url=None, fetcher=FakeFetcher(),
        )


def test_reverse_scan_blocks_without_csam_scanner(
    db, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(get_settings(), "fetcher_backend", "safe")
    monkeypatch.setattr(get_settings(), "csam_scanner_enabled", False)
    sid, aid = authorized_subject(new_workspace.schema_name, ready_asset=True)
    assert reverse_image_scan.run(new_workspace.id, sid, aid) == "blocked"
    with tenant_session(new_workspace.schema_name) as s:
        run = s.scalar(select(DiscoveryRun).order_by(DiscoveryRun.id.desc()))
        assert run is not None
        assert run.status == RunStatus.blocked
        assert run.calls_made == 0


def test_provider_error_does_not_leak_api_key(monkeypatch: pytest.MonkeyPatch):
    def _always_500(url, params=None, timeout=None):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(500, text="boom"))
        )
        try:
            return client.get(url, params=params)
        finally:
            client.close()

    monkeypatch.setattr("api.app.providers.serpapi.httpx.get", _always_500)
    with pytest.raises(ProviderError) as exc:
        SerpApiLensProvider("SECRETKEY123", 1).search("https://storage.example/signed?key=abc")
    message = str(exc.value)
    assert "SECRETKEY123" not in message
    assert "serpapi.com" not in message
    assert "signed" not in message


def test_page_url_javascript_is_dropped(db, new_workspace):
    sid, _ = authorized_subject(new_workspace.schema_name)
    with tenant_session(new_workspace.schema_name) as s:
        candidate = svc.add_link_candidate(
            s, subject_id=sid, run_id=None, provider="p", query="q",
            source_url="https://ok.example/a", page_url="javascript:alert(1)",
        )
        assert candidate is not None
        assert candidate.page_url is None


def test_settings_reject_out_of_range(client: TestClient, auth_header, db, new_workspace):
    base = f"/workspaces/{new_workspace.id}/discovery/settings"
    hdr = auth_header(db.admin_user_id)
    assert client.put(base, headers=hdr, json={"monthly_call_budget": -5}).status_code == 422
    assert client.put(base, headers=hdr, json={"thumbnail_retention_days": 9999}).status_code == 422


def test_settings_is_singleton(db, new_workspace):
    with tenant_session(new_workspace.schema_name) as s:
        svc.get_or_create_settings(s)
        svc.get_or_create_settings(s)
    with tenant_session(new_workspace.schema_name) as s:
        count = s.scalar(select(func.count()).select_from(DiscoverySettings))
    assert count == 1
