"""Wider discovery coverage: 2nd reverse provider, impersonation name sweeps, safe-mode gate."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from worker.discovery import keyword_scan

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.assets import SubjectKeyword
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    RunKind,
    RunStatus,
)
from api.app.models.rights import ConsentRecord, ConsentType, RecordStatus
from api.app.models.subjects import Subject
from api.app.providers import get_reverse_image_providers
from api.app.providers.base import ProviderResponse, ProviderResult
from api.app.providers.serpapi import SerpApiReverseProvider
from api.app.services import discovery as svc
from api.app.services import review as review_svc
from api.tests.discohelpers import authorized_subject


def _mock_httpx_get(fixture: dict):
    def _get(url, params=None, timeout=None):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=fixture))
        )
        try:
            return client.get(url, params=params)
        finally:
            client.close()

    return _get


def test_serpapi_reverse_provider_parses_recorded_fixture(monkeypatch: pytest.MonkeyPatch):
    fixture = {
        "image_results": [
            {
                "original": "https://img.example/a.jpg",
                "link": "https://page.example/a",
                "title": "A",
                "thumbnail": "https://t.example/a.jpg",
            },
            # no "original" → falls back to thumbnail:
            {"thumbnail": "https://t.example/b.jpg", "link": "https://page.example/b"},
            {"link": "https://page.example/c"},  # no image at all → skipped
        ]
    }
    monkeypatch.setattr("api.app.providers.serpapi.httpx.get", _mock_httpx_get(fixture))
    resp = SerpApiReverseProvider("yandex_images", "SECRETKEY", 3).search("https://signed/x")
    assert resp.calls_made == 1 and resp.cost_cents == 3
    assert [r.source_url for r in resp.results] == [
        "https://img.example/a.jpg",
        "https://t.example/b.jpg",  # falls back to thumbnail
    ]
    assert resp.results[0].page_url == "https://page.example/a"
    assert all(r.kind == "image" for r in resp.results)


def test_serpapi_error_body_raises_not_empty(monkeypatch: pytest.MonkeyPatch):
    # A 200 with a top-level "error" (dead/exhausted key) must fail, not look like "no matches".
    from api.app.providers.base import ProviderError

    monkeypatch.setattr(
        "api.app.providers.serpapi.httpx.get",
        _mock_httpx_get({"error": "Invalid API key"}),
    )
    with pytest.raises(ProviderError):
        SerpApiReverseProvider("yandex_images", "k", 1).search("https://signed/x")


def test_second_engine_adds_a_provider(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "provider_backend", "serpapi")
    monkeypatch.setattr(s, "serpapi_key", "k")
    one = get_reverse_image_providers(tineye_enabled=False, second_engine="off")
    two = get_reverse_image_providers(tineye_enabled=False, second_engine="yandex_images")
    assert [p.name for p in one] == ["google_lens"]
    assert [p.name for p in two] == ["google_lens", "serpapi_yandex_images"]


def test_build_keyword_queries_name_sweep_and_safe_mode(db, new_workspace):
    schema = new_workspace.schema_name
    with tenant_session(schema) as s:
        subject = Subject(legal_name="x", stage_names=["StageName"], handles=["@handle"])
        s.add(subject)
        s.flush()
        s.add(SubjectKeyword(subject_id=subject.id, keyword="leaked"))  # a risky keyword
        s.flush()

        unsafe = svc.build_keyword_queries(s, subject, safe_mode=False)
        texts = {q.text for q in unsafe}
        assert "leaked" in texts  # plain identifier query present
        sweep = next(q for q in unsafe if q.text == 'site:instagram.com "StageName"')
        assert sweep.source == "name_sweep" and sweep.suggested_claim == "impersonation"
        # every platform is swept for each identifier
        assert sum(1 for q in unsafe if q.source == "name_sweep") == len(svc.NAME_SWEEP_SITES) * 3

        safe = svc.build_keyword_queries(s, subject, safe_mode=True)
        safe_texts = {q.text for q in safe}
        assert "leaked" not in safe_texts  # risky identifier dropped
        assert 'site:instagram.com "leaked"' not in safe_texts  # risky sweep dropped too
        assert 'site:instagram.com "StageName"' in safe_texts  # non-risky sweeps survive


def test_risky_term_matching_is_word_boundary(db, new_workspace):
    schema = new_workspace.schema_name
    with tenant_session(schema) as s:
        subject = Subject(legal_name="x", stage_names=["Freeman", "Nude Model"], handles=[])
        s.add(subject)
        s.flush()
        safe = {q.text for q in svc.build_keyword_queries(s, subject, safe_mode=True)}
    assert "Freeman" in safe  # contains "free" but not as a whole word → kept
    assert 'site:instagram.com "Freeman"' in safe
    assert "Nude Model" not in safe  # "nude" is a whole word → dropped


def test_second_provider_respects_budget(db, new_workspace, monkeypatch: pytest.MonkeyPatch):
    import worker.discovery as wd
    from worker.discovery import reverse_image_scan

    schema = new_workspace.schema_name
    sid, aid = authorized_subject(schema, ready_asset=True)
    with tenant_session(schema) as s:
        settings = svc.get_or_create_settings(s)
        settings.monthly_call_budget = 1  # only 1 of 2 providers may run

    calls = {"n": 0}

    class _Counting:
        def __init__(self, name: str) -> None:
            self.name = name

        def search(self, image_url: str) -> ProviderResponse:
            calls["n"] += 1
            return ProviderResponse(
                results=[
                    ProviderResult(source_url=f"https://x.example/{self.name}.png", kind="image")
                ],
                calls_made=1,
                cost_cents=1,
            )

    monkeypatch.setattr(
        wd, "get_reverse_image_providers", lambda **k: [_Counting("a"), _Counting("b")]
    )

    assert reverse_image_scan.run(new_workspace.id, sid, aid) == "completed"
    assert calls["n"] == 1  # budget 1 caps a 2-provider scan to a single call
    with tenant_session(schema) as s:
        run = s.scalar(
            select(DiscoveryRun)
            .where(DiscoveryRun.kind == RunKind.reverse_image)
            .order_by(DiscoveryRun.id.desc())
        )
        assert run is not None
        assert run.status == RunStatus.partial and run.calls_made == 1


def test_cross_provider_url_dedupe(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema)
    with tenant_session(schema) as s:
        first = svc.add_link_candidate(
            s, subject_id=sid, run_id=None, provider="google_lens", query=None,
            source_url="https://dupe.example/x?utm_source=a", page_url=None,
        )
        # Same canonical URL from a different provider → deduped.
        second = svc.add_link_candidate(
            s, subject_id=sid, run_id=None, provider="serpapi_yandex_images", query=None,
            source_url="https://dupe.example/x", page_url=None,
        )
    assert first is not None
    assert second is None


def test_keyword_scan_tags_name_sweep_candidates(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, handles=("@star",))
    assert keyword_scan.run(new_workspace.id, sid) == "completed"
    with tenant_session(schema) as s:
        sweeps = list(
            s.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.source == "name_sweep")
            )
        )
    assert sweeps, "expected name-sweep candidates"
    assert all(c.suggested_claim == "impersonation" for c in sweeps)
    assert any("site:" in (c.query or "") for c in sweeps)


def test_inbox_prefers_candidate_suggested_claim_when_supported(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema)
    with tenant_session(schema) as s:
        # Make impersonation a SUPPORTED claim: active authorization (from helper) + enforcement
        # consent.
        s.add(
            ConsentRecord(
                subject_id=sid, type=ConsentType.enforcement, file_key="k", file_name="c.pdf",
                content_type="application/pdf", signer_name="x",
                signed_date=date(2026, 1, 1), status=RecordStatus.active,
            )
        )
        s.add(
            DiscoveryCandidate(
                subject_id=sid, run_id=None, provider="google_search", kind=CandidateKind.link,
                source_url="https://x.example/a", source_key="ns1", source="name_sweep",
                suggested_claim="impersonation",
            )
        )
        s.flush()
        items = review_svc.list_inbox(s)
    item = next(i for i in items if i.candidate.source == "name_sweep")
    assert "impersonation" in item.supported_claims
    assert item.suggested_claim == "impersonation"


def test_discovery_settings_exposes_safe_mode(
    client: TestClient, auth_header, db, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(get_settings(), "csam_scanner_backend", "fake")  # not a real scanner
    r = client.get(
        f"/workspaces/{new_workspace.id}/discovery/settings",
        headers=auth_header(db.admin_user_id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["safe_mode"] is True
    assert body["second_reverse_engine"] == "off"
