# ADR 0001: Slice 0 support dependencies

- **Status:** Accepted
- **Date:** 2026-09-23
- **Context:** Slice 0 (scaffold). CLAUDE.md requires an ADR for dependencies beyond the
  named stack (FastAPI, Celery, Pydantic v2, SQLAlchemy 2, Alembic, React/Vite/Tailwind,
  Clerk, etc.).

## Decision

Add these support libraries, all standard and low-risk:

**Backend**
- `pydantic-settings` — typed env/config loading (the Pydantic v2 settings split-out).
- `psycopg[binary]` — Postgres driver for SQLAlchemy 2 (`postgresql+psycopg`).
- `PyJWT` + `cryptography` — verify Clerk RS256 session JWTs against JWKS.
- `httpx` — HTTP client (JWKS fetch now; providers later).
- `boto3` — Cloudflare R2 access (S3-compatible); config only in Slice 0, used from Slice 3.
- `typer` — the small operational CLI (`vg migrate`, `seed-first-admin`, `create-workspace`).
- Dev: `honcho` (Procfile runner for `make dev`), `ruff`, `mypy`, `pytest`, `pytest-asyncio`.

**Frontend**
- `@clerk/clerk-react` — staff auth in the SPA.
- `tailwindcss` (+ `postcss`, `autoprefixer`) — styling, per the stack.
- `vitest`, `@testing-library/react`, `jsdom` — frontend tests.
- `eslint`, `typescript-eslint`, `typescript` — lint + typecheck.

## Consequences

- No dependency outside this list is added without a new ADR.
- `boto3` and provider SDKs are declared but unused until their slices; no dead runtime code.
