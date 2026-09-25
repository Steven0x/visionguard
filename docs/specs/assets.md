# Spec: Assets & Fingerprints (Slice 3, images only)

Status: implemented in Slice 3. Source of truth for reference-image upload, fingerprinting,
and per-subject text identifiers. Behaviour changes update this file in the same PR.

## Goal

Staff upload a subject's reference photos; a background worker fingerprints each one so later
slices can find copies on the web. Plus per-subject keywords for keyword discovery.

## Not face recognition (read this)

These are **whole-image** fingerprints — a SHA-256, a perceptual hash (pHash), and a
**whole-image OpenCLIP embedding** — used to match **copies of the same photo**. This slice
performs **no face detection, no face cropping, and no face-specific embedding**. It is not a
biometric identifier pipeline.

- Assets are **not** wired into `purge_biometric_data` (the biometric-consent revocation hook).
  This is a deliberate decision for Slice 3.
- Open question for counsel (see `docs/legal/claims-matrix.md`): *are whole-image CLIP
  embeddings of photos that happen to contain faces "biometric identifiers" under BIPA/CUBI?*
  If counsel later says yes, wire asset-embedding deletion into `purge_biometric_data` and
  gate embedding on biometric consent.

**Video is out of scope** for Slice 3 (images only); frame extraction is deferred (backlog).

## Roles

`admin` + `reviewer` (with workspace access) may upload/list/delete/retry assets, view
thumbnails and originals, and manage keywords. Every route sits behind `require_workspace_access`
before a tenant session opens.

## Data model (tenant schema)

### `assets`
`id`, `subject_id`→subjects.id, `file_key`, `thumbnail_key`, `file_name`, `content_type`,
`size_bytes`, `status` (`pending` | `processing` | `ready` | `failed`), `sha256` (char(64),
null until processed), `phash` (char(16) hex, null), `embedding` `vector(512)` (null),
`duplicate_of_asset_id` (self-FK, null), `error` (text, null), `attempts` (int default 0),
`created_at`, `updated_at`. Indexes: b-tree on `sha256`; HNSW cosine on `embedding`.

### `subject_keywords`
`id`, `subject_id`→subjects.id, `keyword` (normalized: trimmed, whitespace-collapsed,
lowercased), `created_at`, `unique(subject_id, keyword)`.

Both are tenant tables with an isolation test each.

## Upload & storage

- Allowed types: **JPEG, PNG, WebP** only, verified by **magic-byte sniffing** (not extension).
- **Decompression-bomb safe:** `Image.MAX_IMAGE_PIXELS = 50_000_000`; `DecompressionBombError`
  and `DecompressionBombWarning` are treated as errors. Every upload is **fully decoded**
  (`Image.open(...).load()`) before anything is written to storage. A truncated, corrupt, or
  over-dimension image → **422**, and nothing is stored.
- Bodies read in capped chunks; over `ASSET_MAX_UPLOAD_BYTES` (~25 MB) → 422.
- The **original** is stored privately, **byte-exact** (for evidence fidelity and hash-based
  duplicate detection), under a tenant-scoped, unguessable key (`{ws_schema}/assets/{uuid}.{ext}`).
  Because the bytes are preserved verbatim, an image-polyglot (valid image prefix + trailing
  payload) survives storage; this is mitigated by never rendering originals inline — they are
  served only as `Content-Disposition: attachment` signed URLs. (Re-encoding to strip trailing
  bytes would break byte-exactness and is deliberately not done.)
- A small **EXIF-stripped JPEG thumbnail** (≤256 px, re-encoded so no GPS/camera metadata
  survives) is stored under `{ws_schema}/thumbnails/…`.
- Downloads are only ever **short-lived signed URLs**:
  - `GET …/assets/{id}/thumbnail` — signed URL, **not audited** (thumbnails aren't evidence;
    gallery polling would flood the audit log).
  - `GET …/assets/{id}/original` — signed URL, **audited `document.downloaded`** (the original
    is the evidence-grade artifact).

## Fingerprinting (background)

On upload the asset is created `pending` and `fingerprint_asset` is enqueued. The worker:
1. **Atomically claims** it: `UPDATE assets SET status='processing' WHERE id=:id AND
   status='pending'`; if 0 rows updated, another worker already has it → stop.
2. Computes `sha256`, `phash`, and a 512-dim L2-normalized OpenCLIP (`ViT-B-32`) embedding.
3. **Exact-duplicate detection:** if another **ready** asset in the workspace has the same
   `sha256`, set `duplicate_of_asset_id` to the earliest such asset (indexed lookup).
4. Stores fields, sets `ready`. On any error it **swallows** → `failed` + `error` +
   `attempts += 1` (never raises).

**Retry:** `POST …/assets/{id}/retry` re-enqueues **only** when `status == failed` and
`attempts < 5`; after 5 attempts it stays `failed`. (Automatic backoff can be added later.)

The embedder is pluggable (`EMBEDDER_BACKEND`): real CLIP in prod (optional `[ml]` deps,
loaded once per worker), a deterministic fake in tests/CI (no torch, no weight download).

## Delete

Hard delete is used in Slice 3 (removes both storage objects + the row, audits
`asset.deleted`). It goes through a guard hook **`can_delete_asset(session, asset)`** which
returns True today; later slices make it return False (→ 409) when the asset is referenced by a
`Match` or `Case`, so evidence can't be deleted out from under an open case.

## Text identifiers

`subject_keywords` holds discovery keywords (e.g. stage name + "leaked"). `GET …/identifiers`
returns the union of the subject's stage names + normalized handles (Slice 1) + keywords for
later keyword discovery.

## Audit

`asset.uploaded`, `asset.deleted`, `keyword.added`, `keyword.removed`, and `document.downloaded`
(original access only). Thumbnail access is intentionally not audited.

## Tests

Isolation (both tables); upload sniff (accept JPEG/PNG/WebP, reject others/oversized);
decompression-bomb + corrupt rejected with nothing stored; fingerprint reaches `ready` with
sha256/phash/512-dim embedding (fake embedder); exact-duplicate flagged; failure→`failed`,
retry→`ready`, retry refused past 5 attempts; atomic-claim no-op on re-run; reviewer-without-
access 403; thumbnail-not-audited vs original-audited; keyword normalize/dedupe + audit.
