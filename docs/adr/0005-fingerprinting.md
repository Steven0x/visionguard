# ADR 0005: Image fingerprinting (Slice 3)

- **Status:** Accepted
- **Date:** 2026-09-24
- **Context:** Slice 3 fingerprints reference images (SHA-256, pHash, and a whole-image
  OpenCLIP embedding in pgvector) so later slices can match copies. CLAUDE.md's stack names
  pgvector and OpenCLIP; heavy ML weights must not slow or bloat CI.

## Decisions

- **Dependencies.** Core adds `pgvector` (SQLAlchemy `Vector` type), `Pillow` (decode,
  thumbnail, EXIF strip), and `numpy` (pHash DCT). A new optional extra **`[ml]` =
  `torch`, `open-clip-torch`** is installed only on the worker in production. pHash is
  implemented with numpy alone (no scipy/imagehash).
- **Fake embedder in CI.** `embedder.get_embedder()` returns a deterministic `FakeEmbedder`
  when `EMBEDDER_BACKEND=fake` (set in tests/CI), else a `ClipEmbedder` that **lazily** imports
  `open_clip`/`torch` and loads `ViT-B-32` once per process. The embedder module never imports
  torch at top level, so it imports fine without `[ml]`; CI installs `.[dev]` only — no torch,
  no weight download.
- **pgvector + HNSW.** `assets.embedding` is `vector(512)`, L2-normalized, with an HNSW cosine
  index (`vector_cosine_ops`) — no training step (unlike IVFFlat). The `vector` extension is
  created once in a public-scope migration; the type resolves from tenant schemas via the
  default search_path.
- **Whole-image, not face.** These embeddings are whole-image copy-matching fingerprints. This
  slice does no face detection/cropping/face-embedding, and assets are **not** wired into
  `purge_biometric_data`. A BIPA/CUBI question is logged for counsel (claims matrix). See
  `docs/specs/assets.md`.

## Note on raw SQL and schemas

CLAUDE.md forbids raw SQL that names a schema — **for application code**. **Migrations are the
sanctioned exception** (they already run `CREATE SCHEMA`, the audit `REVOKE`, and now the HNSW
`CREATE INDEX`), and they use the validated `current_schema()` (matching `^ws_[a-z0-9_]+$`), not
`schema_translate_map`. This does not weaken the app-code rule.

## Consequences

- CI stays light (no torch); prod workers run `pip install -e '.[ml]'`.
- Re-embedding on a model/version change is a future migration/backfill concern.
