# ADR 0006: Discovery v1 — SSRF fetcher, providers, budget

- **Status:** Accepted
- **Date:** 2026-09-24
- **Context:** Slice 4 fetches arbitrary URLs from the open web (found pages/images) and calls
  external search providers. This is the highest-risk surface so far: SSRF, untrusted images,
  cost blow-ups, and illegal content.

## Decisions

- **Single SSRF-safe fetcher** (`api/app/net/`). Pure IP/URL validation (`ssrf.py`) is separated
  from the transport (`fetcher.py`) so the rules are exhaustively unit-tested with a
  monkeypatched resolver (no network in CI). Rules: http/https + ports 80/443 only; resolve DNS
  once and **connect to the pinned IP** (defeats DNS rebinding); block loopback/private/
  link-local/CGNAT/multicast/reserved/IPv6-ULA and the cloud metadata address; re-validate every
  redirect hop (max 3); timeouts, response-size cap, content-type allowlist; no cookies/creds.
  Behind a `Fetcher` Protocol with a `FakeFetcher` for tests.
- **Providers behind an interface** (`api/app/providers/`). `SerpApiLensProvider` (reverse
  image), `SerpApiSearchProvider` (keyword), `TinEyeProvider` (flagged). Each returns
  `(results, calls_made, cost_cents)` so budget/cost accounting is uniform. Fakes for tests,
  selected by `PROVIDER_BACKEND=fake`. 429/5xx backoff in the real clients.
- **Authorization gate everywhere.** Manual intake and every scan require an active agent
  authorization (`subject_enforcement`). No exceptions — intake 403s, scans record `blocked`.
- **Monthly per-workspace call budget, hard stop at the boundary.** Jobs check month-to-date
  `calls_made` before each provider call and stop mid-run (`partial`) at the cap, or make zero
  calls (`blocked`) if already over. Cost is estimated per provider from config.
- **Minimize retained data.** For image candidates we store only fingerprints (sha256, pHash,
  whole-image CLIP embedding) + a private, signed-URL-only, retention-bounded thumbnail — never
  the full-resolution found file.
- **CSAM scanner deferred, choke point reserved.** All fetched images pass through
  `add_image_candidate`, the single place a PhotoDNA-style scan + NCMEC routing will run before
  storage/display. Required before production (backlog).

## Consequences

- No new dependency (httpx already present). CI runs with `FETCHER_BACKEND=fake` +
  `PROVIDER_BACKEND=fake` (plus fake storage/embedder) — fully offline.
- Real crawling is blocked until the CSAM scanner lands.
