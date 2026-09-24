# ADR 0004: Object storage for legal documents

- **Status:** Accepted
- **Date:** 2026-09-23
- **Context:** Slice 2 stores uploaded legal documents (rights, consent, authorization PDFs/
  images). CLAUDE.md's stack names Cloudflare R2 for assets. We need the same code to work in
  local dev/tests without R2 credentials, with safe access controls.

## Decision

- **One S3-compatible interface, two backends.** A `Storage` Protocol
  (`api/app/storage/base.py`) with an `S3Storage` implementation over **boto3** (already a
  dependency). Dev/tests run **MinIO** (docker-compose service); production points the same
  client at **Cloudflare R2** (`vg-assets` bucket). Only endpoint/keys/bucket differ, selected
  by `STORAGE_*` settings. No new dependency.
- **Unguessable, tenant-scoped keys:** `{ws_schema}/{kind}/{uuid4hex}.{ext}`. The workspace
  schema segment is validated by the existing `validate_schema_name`; the uuid makes keys
  unguessable. Objects are never enumerated to clients.
- **No public object URLs.** Downloads are served only as **short-lived presigned GET URLs**
  (default 300 s, `Content-Disposition: attachment`), and only after the caller passes the
  workspace-access check and the record is found in the tenant schema. Issuing a URL is
  audited (`document.downloaded`).
- **Upload safety:** allowed content types are PDF/JPEG/PNG, verified by **magic-byte
  sniffing** (not the extension or the client-declared type); no SVG/HTML. Bodies are read in
  capped chunks and rejected past `STORAGE_MAX_UPLOAD_BYTES` before being buffered whole
  (same pattern as the Slice 1 CSV upload).

## Consequences

- CI adds a MinIO service container and a bucket-create step; storage-backed tests hit MinIO,
  while pure-logic tests need no storage.
- The evidence bucket (`vg-evidence`, object-lock) is separate and arrives in Slice 7; Slice 2
  uses `vg-assets` only.
- Presigned URLs bypass the app for the actual byte transfer — acceptable because the URL is
  short-lived, single-object, and issued only post-authorization.
