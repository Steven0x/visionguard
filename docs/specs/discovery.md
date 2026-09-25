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
   **TinEye** is used only when `discovery_settings.tineye_enabled` (off by default).
3. **Keyword** search from the subject's identifiers (Slice 3 `keywords.identifiers`) via
   **SerpApi Google**. Stored as `link` candidates.

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
review. Dedupe: `unique(subject_id, source_url)` (+ sha256 for images).

Thumbnails of **found content may be sensitive**: stored **private**, served only via
**short-lived signed URLs** (not audited — review galleries poll), and deleted after
`thumbnail_retention_days` (default 90) by a daily cleanup beat.

## CSAM (pre-production requirement)

Found-content thumbnails are ingested from the open web and may include illegal imagery.
**Before production**, every fetched image MUST pass **PhotoDNA-style CSAM hash-scanning**
before it is stored or displayed; a positive match must be routed to the **NCMEC report path**
and never stored or shown (CLAUDE.md #7). Slice 4 **defers the scanner** (tracked in
`docs/BACKLOG.md`) but is built to accommodate it: images pass through a single choke point
(`add_image_candidate`) where the scan will run, and nothing beyond a thumbnail is retained.

## Jobs, budget, cost

- Celery **beat**: `dispatch_scheduled_scans` (hourly) enqueues per-workspace scans whose
  `scan_frequency` (`off`/`daily`/`weekly`) is due; `cleanup_expired_thumbnails` (daily).
- **Monthly call budget** per workspace (`monthly_call_budget`) with a **hard stop at the
  boundary**: before each provider call the job checks month-to-date `calls_made`; it makes
  calls until the cap then stops mid-run (`partial`); if already at/over budget it makes zero
  calls (`blocked`).
- Each run records `provider`, `calls_made`, `estimated_cost_cents`, `candidates_found`, and
  `status`. Providers back off on 429/5xx. Provider + fetcher are behind interfaces; tests use
  fakes (no network).

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
