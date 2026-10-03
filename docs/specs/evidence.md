# Spec: Evidence capture (Slice 7)

Status: draft. Captures a case's infringing page as tamper-evident, write-once evidence:
full-page screenshot, rendered HTML, MHTML archive, metadata — SHA-256 hashed, manifested, and
RFC 3161 timestamped, stored in an object-locked bucket with a chain-of-custody log. Adapts
`ops/capture/capture.py`.

Non-negotiables in play: **evidence is immutable** (CLAUDE.md #6 — write-once, hashed,
timestamped, never edited, only superseded), **minimize sensitive data / never store CSAM** (#7
— fail-closed CSAM gate, restricted access), **tenant isolation** (#5), **SSRF-safe egress**
(Slice 4 rules apply to *all* browser traffic).

## Capture

`capture_evidence(workspace_id, capture_id)` (Celery, eager-safe, never raises):
- A **fresh browser context per capture** — no cookies/storage, `accept_downloads=False`,
  `service_workers="block"`, WebRTC disabled (launch args, so no local-network probing / IP
  leak), WebSocket connections blocked, `file:`/`data:`/`chrome:` schemes blocked, nav + idle
  timeouts, a max page height cap on the full-page screenshot.
- Saves: `screenshot.png`, `page.html` (rendered DOM), `page.mhtml` (archive), `meta.json`
  (requested/final URL, HTTP status, title, visible counts where parseable, capture times, tool
  version, actor).
- Backend behind `CAPTURE_BACKEND` (`playwright` | `fake`); tests/CI use `fake` (deterministic
  bytes, no browser).

### SSRF — all browser traffic (CLAUDE.md #5)
The browser fetches subresources and follows its own DNS, so validating a URL then calling
`route.continue_()` would leave a **DNS-rebinding** hole. Instead the `context.route("**/*")`
handler:
- **aborts every non-GET request**, and
- for GET, fetches through the Slice 4 **`SafeFetcher`** (resolve-once + pinned-IP connect,
  per-redirect-hop re-validation, size cap, no credentials) and **`route.fulfill()`s** with the
  result. A blocked target (`SsrfError`) → `route.abort()`.
This means the browser never opens its own socket to a target; the pinned-IP fetch is the only
egress. `service_workers="block"`, disabled WebRTC, and blocked WebSockets close the remaining
non-HTTP egress paths. The pure decision (`fulfill_or_abort(method, url, fetcher)`) is unit-
tested against `http://169.254.169.254/` and private-IP subresources with the fake fetcher.
(Non-image/HTML subresources the SafeFetcher rejects are aborted — captures may render
unstyled; a safe, fail-closed tradeoff.)

### CSAM gate (fail-closed, same as Slice 4)
`capture_csam_ready()` = `CAPTURE_BACKEND == "fake"` or `csam_scanner_enabled`. In production
(real capture) without a configured scanner, capture **refuses to seal** → the capture row is
`failed` and nothing is stored. Applies to auto/recapture/proof-of-removal **and manual
uploads**. All evidence is restricted-access: signed-URL only, every access custody-logged.

### Triggers
- **Case confirmed** → automatic capture (`kind=auto`).
- **Manual recapture** (`kind=recapture`).
- **Moving to Removed** → proof-of-removal capture (`kind=proof_of_removal`).
- **Manual upload** for login-walled pages (Instagram etc.): staff upload a screenshot + an
  attestation note; the image is validated with the Slice 3 pipeline (content sniff, full
  decode, decompression-bomb limits) and sealed the same way (`kind=manual_upload`).

## Sealing & storage

- SHA-256 of every artifact → a **manifest** (sorted, deterministic) → SHA-256 of the manifest
  → an **RFC 3161 token** over the manifest bytes (`TSA_BACKEND` = `rfc3161` | `fake`; the real
  client — sigstore's `rfc3161-client` — tries several TSAs, first answer wins). If every TSA
  fails → `timestamp_status = untimestamped`, retried by a daily beat task
  (`retry_untimestamped_captures`). **Verification anchors trust to roots pinned in the repo**
  (`api/app/evidence_roots/`), not the CA embedded in the token: the signer must carry the
  `timeStamping` EKU and chain to a pinned root, and the signature must cover exactly the manifest
  bytes — so a forged self-signed token can't "verify" (CLAUDE.md #6). Configured TSAs are
  freetsa.org + sigstore; adding one means pinning its root. See ADR 0009.
- **Write-once evidence bucket** (`STORAGE_EVIDENCE_BUCKET`, separate from assets): `seal_object`
  **refuses to overwrite an existing key** and, on S3/R2/MinIO, writes with **object-lock
  retention** (dev MinIO: bucket created with versioning + object lock, GOVERNANCE mode ~1 day;
  prod R2: long retention, config). `FakeEvidenceStorage` refuses overwrites so a test proves
  write-once. Evidence is never edited — a changed page is a new capture.
- **Chain of custody** (`custody_events`, append-only): every capture / access / download /
  export / verification logs who, when, what, and why (a reason where the action is initiated
  by a human).

## Case integration

- **`requires_evidence_pack(session, case)`** (fills the Slice-6 placeholder): True iff the case
  has ≥1 `sealed` capture with `capture_finished_at ≥ now − EVIDENCE_FRESHNESS_DAYS` (config,
  default **7**). A case therefore can't move to **Filed** without a fresh sealed capture.
- **Evidence-pack PDF** per case (captures, hashes, timestamps, custody log): **admin-only**,
  **requires a reason** (custody-logged as `exported`). Screenshots of captures flagged
  **sensitive** (the default) are **blurred/excluded** unless the admin **explicitly opts in**
  (that choice is also logged).
- **Standalone verify** (`vg verify-evidence <case_id> <capture_id>` CLI + a verify endpoint):
  re-hashes every artifact from storage and re-checks the manifest hash + timestamp token;
  logs a `verified` custody event.

## Data model (migration `0012_tenant`; isolation tests for all three)

- **`evidence_captures`**: `case_id` FK, `kind`, `status` (`pending|sealed|failed`), `sensitive`
  (default true), `requested_url`, `final_url`, `http_status`, `page_title`, `visible_counts`
  (JSONB), `tool_version`, `capture_started_at/finished_at`, `captured_by_staff_id`,
  `manifest_sha256`, `timestamp_status` (`ok|untimestamped`), `tsa_url`, `tsa_time`, `error`.
- **`evidence_artifacts`**: `capture_id` FK, `name`, `object_key`, `sha256`, `content_type`,
  `size_bytes`.
- **`custody_events`** (append-only): `capture_id` FK, `case_id`, `action`, `actor_staff_id`,
  `reason`, `detail`, `created_at`.

## API (`/workspaces/{id}/cases/{cid}/evidence`, admin+reviewer unless noted)
`GET /evidence` (list), `POST /recapture`, `POST /upload` (multipart file + note),
`GET /evidence/{eid}` (artifacts + hashes + timestamp + custody), `GET
/evidence/{eid}/artifacts/{name}` (signed URL; custody `downloaded`), `GET /evidence/{eid}/verify`
(custody `verified`), `GET /evidence/pack.pdf?reason=&include_sensitive=` (**admin**; custody
`exported`).

## Out of scope (later)
Real CSAM/PhotoDNA scanner body (pre-production, tracked in BACKLOG); re-upload watch /
reappearance auto-capture (Slice 9); metrics (Slice 10).
