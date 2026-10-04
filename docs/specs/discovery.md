# Spec: Discovery v1 (Slice 4)

Status: implemented in Slice 4. Source of truth for candidate discovery — manual URL intake,
reverse-image and keyword scans, the SSRF-safe fetcher, and per-workspace scan budgets.
Behaviour changes update this file in the same PR.

## Goal

Turn a subject's fingerprinted reference assets + text identifiers into **candidate matches**:
staff paste found URLs, and scheduled jobs run reverse-image (SerpApi Google Lens; TinEye
behind a flag) and keyword (SerpApi Google) searches. Candidates feed the Slice-5 review inbox.

## Authorization gate (hard rule)

Discovery — **manual intake and every automated scan** — runs only for a subject with an
**active agent authorization** (`services/claim_support.subject_enforcement`, Slice 2).
Searching for, or recording found content for, an unauthorized subject is not allowed:
- intake / scan endpoints → **403** (`DiscoveryNotAuthorized`);
- a scheduled or triggered scan on an unauthorized subject records a `blocked` run and makes
  **zero provider calls**.
This is tested.

## Roles

`admin` + `reviewer` (with workspace access): intake, trigger scans, view candidates + runs,
view candidate thumbnails. **admin only**: edit discovery settings (budget, frequency, TinEye).
All routes sit behind `require_workspace_access`.

## Sources

1. **Manual URL intake** — single or bulk paste, **max 200 URLs per batch**. Each URL is
   canonicalized (lowercase scheme/host, drop default ports + fragment, strip tracking params
   like `utm_*`, `gclid`, `fbclid`) and deduped (within the batch and against existing
   candidates). Stored as `link` candidates.
2. **Reverse image** per **ready** asset via **SerpApi Google Lens** (visual + exact matches).
   A **second SerpApi reverse engine — Yandex Images** — is per-workspace configurable via
   `discovery_settings.second_reverse_engine` (`off` | `yandex_images`, default **`off`**;
   `SerpApiReverseProvider`). Yandex reverse image search is **face-similarity-heavy**, so it is
   **treated as biometric** (CLAUDE.md #1): it runs for a subject's asset only when **all** hold —
   (a) the workspace admin has explicitly opted in by setting `second_reverse_engine=yandex_images`
   (the change is **audited**: `discovery.second_engine_changed`); (b) the subject has **active
   biometric consent and is not geo-blocked** (`biometric_features_enabled`); and (c) the subject
   has **no sensitive case** (CLAUDE.md #7) — **any** case with `sensitive=True`, including
   terminal/closed ones (fail-closed; `_has_sensitive_case` does not filter by case state). The
   per-subject gate is `services/discovery.yandex_reverse_allowed`, enforced in
   `reverse_image_scan` — **the sole call site** (Google Lens is unaffected). The gate currently
   reuses the subject's **generic biometric consent**; it does **not** yet capture a Yandex- or
   Russia-specific cross-border-transfer disclosure, so counsel's answer to the claims-matrix open
   question may require a distinct consent before the opt-in can be honored. **Bing was removed**
   (no robust SerpApi Bing reverse-by-URL engine; Bing's APIs were retired — CLAUDE.md). **TinEye**
   is used only when `discovery_settings.tineye_enabled`
   (off by default). All providers run under the one per-workspace budget; results are **deduped by
   canonical URL** across providers (the `unique(subject_id, source_key)` constraint +
   `_candidate_exists`).
3. **Keyword** search via **SerpApi Google**, plus **impersonation name sweeps**:
   `site:<platform> "<term>"` for `instagram.com, tiktok.com, x.com, facebook.com, t.me`
   (`build_keyword_queries` → `NAME_SWEEP_SITES`). Both avoid bare single-token first names, which
   match thousands of unrelated results:
   - **Plain queries** run standalone only for **specific** terms — handles, explicit keywords, and
     full (multi-token) stage names. A **single-token stage name** ("Steven") never runs alone; it
     runs **only combined with a qualifier** — a handle, the full name, or a platform term
     (`PLATFORM_QUALIFIERS` = onlyfans/fansly) when risky terms are allowed (not safe mode).
   - **Name sweeps** use only **handles** (exact, quoted) and **full, multi-token names**
     (`services/discovery.name_sweep_terms`) — never a bare first name.
   When a subject has no precise term (no handle, no full name), name sweeps are disabled, a lone
   single-token name is unsearchable in safe mode, and the subject carries a `name_sweep_warning`
   ("add a full name or handle…"), surfaced on `SubjectOut` and shown in the discovery UI. Sweep
   candidates are tagged `source="name_sweep"` with `suggested_claim="impersonation"` (the review
   inbox prefers that claim when supported). Stored as `link` candidates.

## SSRF-safe fetcher

**Every outbound fetch** of a found page or image goes through `api/app/net/fetcher.py`:
- **Scheme** http/https only; **ports** 80/443 only.
- **Resolve DNS once**, validate every resolved IP, then **connect to the pinned IP** (Host
  header + TLS SNI preserved) so a DNS rebind can't swap the target between check and connect.
- **Blocked IP ranges:** loopback, private (RFC1918 + IPv6 ULA `fc00::/7`), link-local
  (`169.254/16`, `fe80::/10`), **CGNAT `100.64/10`**, multicast, reserved, unspecified,
  broadcast, and the **cloud metadata** address `169.254.169.254` (+ IPv6 form).
- **Redirects** followed manually, max **3 hops**, **re-validating** scheme/port/host/IP on
  each hop. `follow_redirects=False` on the client.
- **No cookies, no credentials/auth** forwarded; connect + read **timeouts**; a **response
  size cap** (streamed, aborted when exceeded); a **content-type allowlist** (`image/*`,
  `text/html`).
Each block is unit-tested with a monkeypatched resolver — no real network in tests/CI.

## Candidates

`discovery_candidates` stores: `subject_id`, `run_id`, `provider`, `query`, `kind`
(`image` | `link`), `source_url`, `page_url`, and for **image** candidates only:
`sha256`, `phash`, `embedding` (whole-image CLIP, Slice 3), `thumbnail_key`, `content_type`.
**We never store the full-resolution found file** — only fingerprints + a small thumbnail for
review. Dedupe: `unique(subject_id, source_url)` (+ sha256 for images), keyed on the **canonical**
URL (`canonicalize_url`: lowercased scheme/host, default ports + fragment + tracking params
dropped, query sorted). **Telegram** gets extra canonicalization: `telegram.me`/`www.` aliases
collapse to `t.me`, and the channel-preview pagination/search params (`before`, `after`, `q`) are
dropped — so SerpApi's dozens of `t.me/s/<channel>?before=…` hits for one channel (or one message)
dedupe to a single candidate instead of flooding the inbox. Distinct messages
(`t.me/s/<channel>/<id>`) stay distinct.

Thumbnails of **found content may be sensitive**: stored **private**, served only via
**short-lived signed URLs** (not audited — review galleries poll), and deleted after
`thumbnail_retention_days` (default 90) by a daily cleanup beat.

## CSAM (pre-production requirement)

Found-content thumbnails are ingested from the open web and may include illegal imagery.
**Before production**, every fetched image MUST pass **PhotoDNA-style CSAM hash-scanning**
before it is stored or displayed; a positive match must be routed to the **NCMEC report path**
and never stored or shown (CLAUDE.md #7). Slice 4 **defers the scanner** (tracked in
`docs/BACKLOG.md`) but **fails closed in code, not just docs**: `add_image_candidate` (the
single choke point where found imagery enters storage) refuses to store when the real `safe`
fetcher is used and `CSAM_SCANNER_ENABLED` is false — so a reverse-image scan in production
records a `blocked` run and stores nothing until the scanner is wired. The fake fetcher
(tests/CI) is exempt. Nothing beyond a thumbnail is ever retained.

### Safe mode (no real scanner) — risky-term suppression + staff banner
When **no real CSAM scanner is connected** (`csam_scanner_backend` is `none`/`fake` — i.e.
`csam.safe_discovery_mode()` is true), discovery still runs locally, so two guards apply
(CLAUDE.md #7): (a) **risky-term queries are suppressed** — any keyword/name-sweep query whose
words include a term in `discovery_risky_terms` (`leaked, onlyfans, nude, mega, telegram, …`;
matched on **word boundaries** so a name like "Freeman" isn't dropped for containing "free") is
dropped in `build_keyword_queries`, so staff don't pull the riskiest imagery through a fake
scanner; and (b) the discovery UI shows a **banner**: *"CSAM scanner not connected — test with
your own photos only."* (`GET /discovery/settings` exposes a read-only `safe_mode`). Reverse
image scans are unaffected by (a) — they still run through the `add_image_candidate` CSAM choke
point, which fails closed until a scanner is wired.

## Jobs, budget, cost

- Celery **beat**: `dispatch_scheduled_scans` (hourly) enqueues per-workspace scans whose
  `scan_frequency` (`off`/`daily`/`weekly`) is due; `cleanup_expired_thumbnails` (daily).
- **Monthly call budget** per workspace (`monthly_call_budget`) with a **hard stop at the
  boundary**: budget is **reserved** under the settings row lock before any provider call (so
  concurrent scans can't overrun); if already at/over budget it makes zero calls (`blocked`), and
  a scan reserving fewer than its full work list ends `partial`.
- **Only calls SerpApi actually bills count** against `calls_made`/`estimated_cost_cents`. The
  reservation is **reconciled down** to the billed total when the run finishes: a query that
  returns an **empty result set** (SerpApi answers `200` + a benign "hasn't returned any results"
  error — common for `site:` name sweeps) is **not billed** and is recorded as 0 calls / 0 cost,
  **not** as a failure. A real provider failure (bad key, quota, rate limit, HTTP/network) stops
  the run, records `status=failed` with a **sanitized reason** on `run.error` (surfaced in the UI),
  and counts only the calls billed before it — never the reserved amount.
- Each run records `provider`, `calls_made`, `estimated_cost_cents`, `candidates_found`, `status`,
  and (on failure) `error`. **Transient SerpApi failures** (timeouts, 429, 5xx) are **retried with
  exponential backoff** (`serpapi_max_retries`, default 3) under a longer per-request timeout
  (`serpapi_timeout_seconds`, default 30s) before the run fails — results already collected from
  earlier queries in the run are kept. Provider + fetcher are behind interfaces; tests use fakes
  (no network).
- **Per-run per-source cap** (`discovery_max_candidates_per_source_per_run`, default 25): each run
  creates at most N new candidates per `source` (`reverse` | `keyword` | `name_sweep`), so one
  broad/bad query can't flood the inbox (and reverse stops fetching + CSAM-scanning once reached).
- **Cost per provider** is logged per call (`discovery.provider_cost provider=… calls=…
  cost_cents=…`, no secrets) and a `cost_by_provider` breakdown is folded into the
  `discovery.scan_run` audit meta when more than one provider runs.

## Local real-discovery profile (dev)

To exercise the real pipeline locally, set these in the gitignored `.env` (the SerpApi key stays
there — **never committed**) and install the ML + browser extras:

```
PROVIDER_BACKEND=serpapi     # SerpApi Google Lens + optional 2nd engine
FETCHER_BACKEND=safe         # SSRF-safe fetcher
CAPTURE_BACKEND=playwright   # evidence screenshots/HTML
TSA_BACKEND=rfc3161          # RFC 3161 timestamps
EMBEDDER_BACKEND=clip        # OpenCLIP ViT-B-32 (first use downloads the model)
EMAIL_BACKEND=outbox         # never send real mail locally
CSAM_SCANNER_BACKEND=fake    # no real scanner → safe mode (banner + risky-term suppression)
SERPAPI_KEY=…                # your key, in .env only
```
```
pip install -e ".[ml]" && python -m playwright install chromium
```
Safe mode stays on (CSAM fake), so risky-term queries are suppressed and the banner shows —
**test with your own photos only**.

### Exposing assets to reverse-image providers (dev tunnel)
Reverse-image scans hand the provider a **presigned URL to the subject's asset**, which the
provider's servers (Google Lens, Yandex) fetch directly. Locally MinIO presigns a **`localhost`**
URL the providers can't reach, so a real reverse scan returns **0 matches** (not an error — the
provider just sees nothing). For dev, expose MinIO through a **guarded** tunnel:

```
# 1) Use NON-DEFAULT MinIO creds (default minioadmin is a public signing key → forgeable
#    presigns). In .env set a matching pair and restart MinIO + the worker:
MINIO_ROOT_USER=vg-dev            STORAGE_ACCESS_KEY_ID=vg-dev
MINIO_ROOT_PASSWORD=<random>      STORAGE_SECRET_ACCESS_KEY=<same random>
#    docker compose up -d minio minio-setup
# 2) make lens-tunnel      # starts the guarded proxy + a cloudflared quick tunnel
# 3) paste the printed hostname into .env and restart the worker:
DISCOVERY_ASSET_PUBLIC_BASE_URL=https://<name>.trycloudflare.com
```

`make lens-tunnel` (→ `api/app/dev/lens_proxy.py`) does **not** tunnel MinIO directly. It runs a
tiny **allowlist proxy** between the tunnel and MinIO that permits **only** a non-expired
**presigned GET of an object in the assets bucket** and refuses everything else — any other method,
any other bucket (incl. the **evidence** bucket), **bucket listings**, object/bucket sub-resource
ops (acl, tagging, multipart, retention, …), the **console**, and **unsigned** requests (`authorize`,
unit-tested per rejection). It forwards the exact path+query and preserves the incoming Host so
MinIO validates the presign (signed against the tunnel host); it never holds the signing secret.
It **refuses to start** unless `APP_ENV=dev` **and** MinIO is on non-default creds, **auto-stops
after 15 min**, and prints a *"the tunnel is public while running"* warning.

`generate_download_url(..., public_base_url=…)` signs the presigned URL against the tunnel host.
This is **dev-only**: `Settings.dev_lens_asset_base_url` returns the base **only when APP_ENV=dev**,
so the env var has no effect in staging/production. **Production** needs none of this — R2 presigned
URLs are already public, with a short TTL (`storage_signed_url_ttl_seconds`, default 300s).

## Audit

`discovery.intake` (per batch), `discovery.scan_run` (per run, meta: provider/calls/cost/
status), and `discovery.blocked` (gate or budget). Candidate thumbnail views are not audited.

## Data model (tenant schema)

`discovery_settings` (one row/workspace), `discovery_runs`, `discovery_candidates` — all tenant
tables with an isolation test each. FKs to subjects/assets within the tenant schema.

## Tests

SSRF each-block; the authorization gate (intake 403, scan blocked with zero calls); budget hard
stop at boundary; intake canonicalize/dedupe/max-200; reverse-image scan (fakes) → image
candidates with fingerprints + thumbnail; keyword scan (fakes) → link candidates; isolation for
the three tables; audit; candidate thumbnail signed URL + reviewer-without-access 403.
