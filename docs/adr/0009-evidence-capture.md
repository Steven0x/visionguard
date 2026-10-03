# ADR 0009: Evidence capture (Slice 7)

Status: accepted. Context: `docs/specs/evidence.md`, CLAUDE.md #6 (evidence immutable) and #7
(minimize sensitive data / CSAM), Slice 4 SSRF rules.

## Decisions

1. **Backends behind env, fakes in CI.** `CAPTURE_BACKEND` (playwright|fake), `TSA_BACKEND`
   (rfc3161|fake), and a dedicated write-once evidence storage selected by `STORAGE_BACKEND`.
   `playwright`/`rfc3161-client` are lazy-imported (the `capture` extra), so CI runs on fakes with
   no browser/TSA/network. `reportlab` (PDF) is a main dependency (pure-python).

   **Timestamping uses sigstore's `rfc3161-client`** (strict DER, Rust-backed; verifies EC and
   RSA). It replaced `rfc3161ng`, which could not verify EC-signed tokens and mis-encoded the
   signed attributes as BER so verification never actually worked. **Trust is anchored to roots
   pinned in the repo** (`api/app/evidence_roots/tsa_pinned_roots.pem`), NOT to the CA embedded in
   the token: verification picks the signing cert bearing the `timeStamping` EKU, requires it to
   chain to a pinned root, and checks the signature over exactly the manifest bytes; at request
   time it also checks the TSA echoed the request nonce. Without pinning, anyone who could write to
   the evidence store could mint a self-signed token that "verifies" — defeating CLAUDE.md #6. The
   configured TSAs are **freetsa.org and sigstore**, the two whose responses parse under the strict
   parser and whose roots we pin (DigiCert/Sectigo/Apple return a non-DER-sorted certificate SET
   the parser rejects). Adding a TSA means pinning its root. The ops day-1 tool
   (`ops/capture/capture.py`) carries its own copy of the pinned roots in `ops/capture/tsa_roots/`.

2. **Browser SSRF closes the DNS-rebinding hole.** The `context.route` handler doesn't validate
   then `continue_()` (which would let the browser re-resolve + connect). It **aborts non-GET**
   and, for GET, fetches through the Slice 4 **SafeFetcher** (resolve-once + pinned IP, per-hop
   re-validation, size cap) and **fulfills** — the browser never opens its own socket to a
   target. `service_workers="block"`, disabled WebRTC (launch args), blocked WebSockets, and no
   downloads close the remaining egress. The pure `fulfill_or_abort` decision is unit-tested.

3. **Write-once evidence, separate bucket.** `EvidenceStorage.seal_object` refuses to overwrite
   an existing key and (S3/R2/MinIO) writes with object-lock retention (dev MinIO: versioning +
   object lock, GOVERNANCE ~1 day; prod R2: long retention via config). `FakeEvidenceStorage`
   refuses overwrites so a test proves write-once. Evidence is never edited — only superseded.

4. **Sealing = hash + manifest + RFC 3161.** SHA-256 per artifact → deterministic manifest →
   SHA-256 → timestamp token over the manifest. If every TSA fails → `untimestamped`, retried by
   a daily beat task. `verify` re-hashes from storage and re-checks the manifest + token.

5. **CSAM fail-closed at the capture/upload choke point** (`capture_csam_ready()`): in
   production without a configured scanner, capture/upload refuses to store. This is a second
   choke point alongside Slice 4's `add_image_candidate`; both are pre-production blockers.

6. **Restricted access + chain of custody.** All evidence is signed-URL only; every access,
   download, export, and verification writes an append-only `custody_events` row (who/when/what/
   why). The PDF pack is **admin-only, requires a reason**, and blurs sensitive screenshots
   unless the admin explicitly opts in (logged).

7. **`requires_evidence_pack(session, case)` filled** (Slice 6 placeholder): a case can't move
   to `Filed` without a sealed capture newer than `EVIDENCE_FRESHNESS_DAYS` (default 7). Confirm
   auto-captures; moving to Removed captures proof-of-removal.

## Not done here
The real CSAM/PhotoDNA scanner body (pre-production); reappearance auto-capture (Slice 9);
metrics (Slice 10). Non-image/HTML subresources the SafeFetcher rejects are aborted (captures
may render unstyled) — a safe, fail-closed tradeoff.
