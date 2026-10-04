"""Discovery precision/flood controls (real-SerpApi walkthrough follow-up):

- name sweeps require a precise term (handle or full name); single first names are skipped with a
  per-subject warning (surfaced on the subject API);
- t.me pagination/search params canonicalize away so one channel dedupes to one candidate;
- new candidates are capped per run per source so one broad query can't flood the inbox.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from worker import discovery as wd
from worker.discovery import keyword_scan

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.discovery import DiscoveryCandidate
from api.app.models.subjects import Subject
from api.app.providers.base import ProviderResponse, ProviderResult
from api.app.services import discovery as svc
from api.app.services.discovery import (
    build_keyword_queries,
    canonicalize_url,
    name_sweep_terms,
    name_sweep_warning,
)
from api.tests.discohelpers import authorized_subject

# ── #2 name-sweep precision + warning ─────────────────────────────────────────


def test_name_sweep_terms_skips_single_token_names():
    assert name_sweep_terms(["Steven"], []) == []  # too broad
    assert name_sweep_terms(["Steven Nakhwal"], []) == ["Steven Nakhwal"]  # full name ok
    assert name_sweep_terms(["Steven"], ["@stevenn"]) == ["stevenn"]  # handle preferred


def test_name_sweep_warning():
    assert name_sweep_warning(["Steven"], []) is not None
    assert name_sweep_warning([], []) is not None
    assert name_sweep_warning(["Steven Nakhwal"], []) is None
    assert name_sweep_warning(["Steven"], ["@x"]) is None


def test_build_keyword_queries_skips_single_token_name_sweeps(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, stage_names=("Steven",))
    with tenant_session(schema) as s:
        subject = s.get(Subject, sid)
        assert subject is not None
        queries = build_keyword_queries(s, subject, safe_mode=False)
    texts = {q.text for q in queries}
    assert not any(q.source == "name_sweep" for q in queries)  # no flood from "Steven"
    assert "Steven" not in texts  # never a standalone Google query
    assert "Steven onlyfans" in texts  # only combined with a qualifier (risky allowed here)


def test_single_token_stage_name_only_runs_combined_with_a_qualifier(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, stage_names=("Steven",), handles=("@stevenn",))
    with tenant_session(schema) as s:
        subject = s.get(Subject, sid)
        assert subject is not None
        queries = build_keyword_queries(s, subject, safe_mode=False)
    texts = {q.text for q in queries}
    assert "Steven" not in texts  # not standalone
    assert "stevenn" in texts  # the handle itself is specific → standalone
    assert "Steven stevenn" in texts  # combined with the handle
    assert "Steven onlyfans" in texts  # combined with a platform term (risky allowed)


def test_single_token_combined_with_full_name(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, stage_names=("Steven", "Steven Nakhwal"))
    with tenant_session(schema) as s:
        subject = s.get(Subject, sid)
        assert subject is not None
        texts = {q.text for q in build_keyword_queries(s, subject, safe_mode=False)}
    assert "Steven Nakhwal" in texts  # full name standalone
    assert "Steven" not in texts  # single token never standalone
    assert "Steven Steven Nakhwal" in texts  # combined with the full name


def test_single_token_in_safe_mode_needs_handle_or_full_name(db, new_workspace):
    # No handle, no full name, safe mode → platform qualifiers are suppressed, so a lone single
    # token produces NO queries at all and the subject shows the "add a full name or handle" hint.
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, stage_names=("Steven",))
    with tenant_session(schema) as s:
        subject = s.get(Subject, sid)
        assert subject is not None
        texts = {q.text for q in build_keyword_queries(s, subject, safe_mode=True)}
    assert not any("Steven" in t for t in texts)  # nothing searchable for a lone first name
    assert name_sweep_warning(["Steven"], []) is not None  # same hint applies


def test_build_keyword_queries_sweeps_full_name(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, stage_names=("Steven Nakhwal",))
    with tenant_session(schema) as s:
        subject = s.get(Subject, sid)
        assert subject is not None
        queries = build_keyword_queries(s, subject, safe_mode=False)
    sweeps = [q for q in queries if q.source == "name_sweep"]
    assert sweeps and all('"Steven Nakhwal"' in q.text for q in sweeps)


def test_subject_api_exposes_name_sweep_warning(client, auth_header, db):
    header = auth_header(db.admin_user_id)
    base = f"/workspaces/{db.workspace_a.id}/subjects"
    broad = client.post(
        base, headers=header, json={"legal_name": "Steven", "stage_names": ["Steven"]}
    )
    assert broad.status_code == 201
    assert broad.json()["name_sweep_warning"] is not None

    ok = client.post(
        base, headers=header, json={"legal_name": "Steven N", "handles": ["@stevenn"]}
    )
    assert ok.status_code == 201
    assert ok.json()["name_sweep_warning"] is None


# ── #3 t.me canonicalization / dedupe ─────────────────────────────────────────


def test_telegram_pagination_and_search_params_collapse():
    a = canonicalize_url("https://t.me/s/chan?before=100&q=steven")
    b = canonicalize_url("https://t.me/s/chan?before=200")
    c = canonicalize_url("https://t.me/s/chan")
    assert a == b == c == "https://t.me/s/chan"


def test_telegram_distinct_messages_stay_distinct():
    assert canonicalize_url("https://t.me/s/chan/123?before=1") == "https://t.me/s/chan/123"
    assert canonicalize_url("https://t.me/s/chan/123") != canonicalize_url("https://t.me/s/chan/456")


def test_telegram_alias_hosts_normalize_to_t_me():
    assert canonicalize_url("https://telegram.me/chan") == "https://t.me/chan"
    assert canonicalize_url("https://www.t.me/chan") == "https://t.me/chan"


def test_non_telegram_hosts_keep_their_params():
    # The before/q drop is t.me-specific; a normal host keeps its query params.
    assert "before=1" in (canonicalize_url("https://example.com/x?before=1") or "")


def test_telegram_variants_dedupe_to_one_candidate(db, new_workspace):
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema)
    with tenant_session(schema) as s:
        first = svc.add_link_candidate(
            s, subject_id=sid, run_id=None, provider="p", query=None,
            source_url="https://t.me/s/chan?before=100&q=steven", page_url=None,
        )
        second = svc.add_link_candidate(
            s, subject_id=sid, run_id=None, provider="p", query=None,
            source_url="https://t.me/s/chan?before=900", page_url=None,
        )
    assert first is not None and second is None  # same channel → one candidate


# ── #4 per-source per-run cap ─────────────────────────────────────────────────


def test_keyword_scan_caps_candidates_per_source(
    db, new_workspace, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(get_settings(), "discovery_max_candidates_per_source_per_run", 3)
    schema = new_workspace.schema_name
    sid, _ = authorized_subject(schema, handles=("@star",))  # handle → name sweeps enabled

    class _Flood:
        name = "google_search"
        n = 0

        def search(self, query: str) -> ProviderResponse:
            self.n += 1  # distinct URLs per query so nothing dedupes
            results = [
                ProviderResult(source_url=f"https://ex{self.n}-{i}.example/p", kind="link")
                for i in range(10)
            ]
            return ProviderResponse(results=results, calls_made=1, cost_cents=1)

    monkeypatch.setattr(wd, "get_keyword_provider", lambda: _Flood())
    assert keyword_scan.run(new_workspace.id, sid) == "completed"
    with tenant_session(schema) as s:
        rows = s.execute(
            select(DiscoveryCandidate.source, func.count())
            .where(DiscoveryCandidate.subject_id == sid)
            .group_by(DiscoveryCandidate.source)
        ).all()
    counts: dict[str, int] = {source: count for source, count in rows}
    # Each source is capped at 3 even though every query returned 10 distinct results.
    assert counts.get("keyword") == 3
    assert counts.get("name_sweep") == 3
