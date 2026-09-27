# ADR 0010: CSAM scanner interface & per-image choke point

Status: accepted. Context: CLAUDE.md #7 ("Never store or display suspected CSAM. Flag it for
the NCMEC report path and stop processing."), superseding the boolean gates in ADR 0006/0009.

## Decision

Replace the `csam_scanner_enabled` boolean (which merely lifted a gate without scanning) with a
per-image **`CsamScanner`** interface (`api/app/csam.py`):

- `scan_image(bytes) -> ScanOutcome` (`clean | match | error`), never raising — any scanner
  failure becomes `error`. **Callers store/seal ONLY on `clean`.**
- Backends: **`none`** (default) fails every scan closed → nothing stored; **`fake`**
  (dev/test only, refused at config load otherwise) returns a configurable result. A real
  PhotoDNA/Safer backend drops in behind the same interface.
- On **match**: record a **minimized incident** (`csam_incidents`: source/URL/sha256/time only
  — no image or thumbnail column exists) and store nothing; route it to the **admin-only**
  escalation queue for the NCMEC report path. On **error / no scanner**: fail closed.

## Choke points (every place open-web or uploaded imagery would be stored)

1. **Discovery** — `add_image_candidate` scans the fetched image before the thumbnail/
   fingerprint are stored.
2. **Evidence capture** — scanned at the **single browser egress point** (`fulfill_or_abort`
   in the SafeFetcher route handler): every image the browser loads is scanned, so a non-clean
   image is aborted and never enters the page, the screenshot, or the sealed MHTML/HTML archive.
   The composite screenshot is also scanned in the worker as a secondary check.
3. **Manual evidence upload** — scanned before `seal_manual_upload`.
4. **Asset upload (Slice 3)** — scanned in `create_asset` before storing the original or
   thumbnail.

## Residual (pre-production)

- The real scanner backend is still to be built; until it is deployed, production runs with
  `none` and stores nothing from these paths (fail-closed).
- Inline `data:` images embedded directly in captured HTML are not network-fetched, so they
  bypass the egress scan; the composite-screenshot scan is the only gate for them. A real
  scanner integration should additionally scan images extracted from the sealed HTML/MHTML.
