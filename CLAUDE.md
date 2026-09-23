# VisionGuard

VisionGuard finds where a person's images, face and paid content, or a brand's assets, are used without permission, proves it, and gets them removed or paid for. It is an **enforcement product with detection underneath**, not a search engine.

- **Current phase:** Phase 1, the concierge MVP. An internal tool used by VisionGuard staff to serve 5–10 paying agencies. No customer-facing portal yet.
- **Wedge customer:** talent agencies, model agencies and creator management firms (People mode). Brands mode comes in Phase 2–3; don't build for it yet, but don't design it out.
- **Source of truth:** `docs/product-outline.md` (product), `docs/specs/*.md` (per-module specs), `docs/legal/claims-matrix.md` (claim rules), `docs/BACKLOG.md` (build order), `docs/adr/` (decisions).

## Non-negotiables

These are product rules, not preferences. Code that breaks one is wrong even if the tests pass.

1. **Consent before biometrics.** No face template, face embedding or face match may exist for a subject without an active `ConsentRecord` of type `biometric`. Revoking consent deletes templates and embeddings for that subject (hard delete, logged).
2. **No open face search.** Face matching only ever compares found faces against templates of consenting subjects in the same workspace. There is no endpoint that takes an arbitrary face and returns identities.
3. **A human approves every filing.** Nothing is sent to a platform, host or person without a recorded human approval (`approved_by`, `approved_at`) on the action. Automation drafts; people decide.
4. **Every case has a claim.** A case can't move to `Filed` without a `claim_type` from the claims matrix and a rights record that supports it. Never send a DMCA notice for a trademark or likeness issue.
5. **Tenant isolation.** Every query is scoped to a workspace. Schema-per-tenant in Postgres; no cross-tenant joins; tests must prove isolation for every new table. Tenant data is reached **only through ORM tenant sessions** (bound with `schema_translate_map`); **no raw `text()` SQL may name a schema** — translate-map does not rewrite raw SQL, so raw SQL would bypass isolation. The only sanctioned exceptions are provisioning DDL (`CREATE SCHEMA`) and the `audit_log` REVOKE, and both use a name validated against `^ws_[a-z0-9_]+$` first. Schema names are always derived from a trusted workspace id, never from client input. See `docs/adr/0002-tenant-isolation-strategy.md`. The `audit_log` table is **append-only** (no update/delete path; UPDATE/DELETE revoked from the app role).
6. **Evidence is immutable.** Evidence artifacts are write-once: SHA-256 hashed at capture, RFC 3161 timestamped, stored with object lock. They are never edited or overwritten, only superseded by new captures. Chain-of-custody log for every access.
7. **Minimize sensitive data.** Store hashes and fingerprints instead of intimate images wherever possible; encrypt anything that must be kept; set retention periods. Never store or display suspected CSAM. Flag it for the NCMEC report path and stop processing.
8. **Allowlist first.** Check a workspace's allowlist (licensees, authorized resellers, the subject's own accounts) before a match reaches review.
9. **Geo exclusions.** Subjects residing in Illinois or Washington can't have biometric features enabled until counsel clears it. Enforce this in code, not just policy.

## Stack

- **Backend:** Python 3.12, FastAPI, Celery workers, Pydantic v2, SQLAlchemy 2.x, Alembic
- **Data:** Supabase Postgres + pgvector (schema-per-tenant); Upstash Redis (queues, cache); Cloudflare R2 (assets and evidence, object lock for evidence)
- **Auth:** Clerk (staff only in Phase 1)
- **Email:** SendGrid (notices by email; reports)
- **Frontend:** React + TypeScript, Vite, Tailwind; deployed on Vercel
- **Discovery providers:** SerpApi Google Lens, TinEye. Don't design around Bing; its Search APIs were retired Aug 2025.
- **Evidence capture:** Playwright (screenshot, full HTML, page archive)
- **Matching:** perceptual hash (pHash) → OpenCLIP embeddings in pgvector → classifier (rules first; XGBoost once there's labeled data)

Ask before adding a dependency not listed here. Record significant choices as an ADR in `docs/adr/`.

## Domain model (short)

`Workspace` → `Subject` (person or brand) → `RightsRecord` / `ConsentRecord` → `Asset` → `Watch` → `Match` → `Case` → `EvidencePack` + `Action` → `Outcome` / `Recovery`.

Case states: `Discovered → Confirmed | Dismissed`, `Confirmed → Filed`, `Filed → Removed | Countered | Escalated`, `Removed → Monitoring → Discovered (reappears) | Closed`, `Escalated → Recovered | Closed`. Transitions are only allowed through the case service, which enforces the rules above and writes an audit event.

## How to work in this repo

- **One vertical slice at a time.** Pick the next item in `docs/BACKLOG.md`, read its spec, plan it (plan mode) and build UI → API → DB → worker for that slice only.
- **Tests with every change:** unit tests for services, API tests for endpoints, and an isolation test for every new tenant table. Run `make test` before calling anything done.
- **Before committing a slice:**
  1. Run the `reviewer` subagent on the diff.
  2. Run the `red-team` subagent if the slice touches auth, tenancy, subjects, consent, biometrics, evidence, uploads or anything that sends outbound messages.
  3. Run the `claims-checker` subagent if it touches claim selection, notice templates or filing.
  4. Fix what they find, or record why not in the PR description.
- **Keep specs current.** If the implementation has to deviate from a spec, update the spec in the same change.
- **Small commits,** conventional messages (`feat:`, `fix:`, `chore:`, `docs:`).
- **Never commit secrets.** Config comes from environment variables, documented in `.env.example`.

## Commands

(Fill these in as the scaffold lands.)

- `make dev` — run API, worker and frontend locally
- `make test` — full test suite
- `make lint` — ruff, mypy, eslint, tsc
- `make migrate` — apply Alembic migrations to all tenant schemas

## What not to build yet

Customer self-serve portal, billing, the full crawler fleet (start with provider APIs + manual URL intake), Brands mode, deepfake detection models, recovery/CCB automation, EU features. These are Phase 2+.
