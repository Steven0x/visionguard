# Deploy runbook

Operator procedure for shipping VisionGuard. Design rationale is in
[`docs/specs/production.md`](../specs/production.md) and [ADR 0014](../adr/0014-production-deploy.md).
Fly quick reference: [`deploy/fly/README.md`](../../deploy/fly/README.md).

## Topology

| Component | Where | Notes |
| --- | --- | --- |
| API | Fly `visionguard-api` (`docker/api.Dockerfile`) | HTTP; runs the migration release step |
| Worker | Fly `visionguard-worker` (`docker/worker.Dockerfile`) | torch + Playwright; heavier VM |
| Beat | Fly `visionguard-beat` (`docker/beat.Dockerfile`) | **exactly one machine** |
| Postgres | Supabase (pgvector) | **session pooler or direct — not the transaction pooler** |
| Redis | dedicated managed Redis | Celery broker/back end |
| Object storage | Cloudflare R2 | `vg-assets`; `vg-evidence` with object lock |
| Web | Vercel (static) | built from `web/`, headers via `web/vercel.json` |
| Auth | Clerk | staff only; MFA required |

Staging mirrors these with `-staging` names and `*.staging.toml` (same images, fake email, separate
1-day-retention evidence bucket).

## Pre-req: the CSAM gate

Staging and production **refuse to boot until a real CSAM scanner backend is connected** behind the
`api/app/csam.py` interface (CLAUDE.md #7). This is intentional and cannot be bypassed by config.
Until then, only `dev`/`test` (which may use the fake scanner) run. Connecting the real scanner is
tracked as the remaining pre-production task.

## Secrets

Never commit secrets; set them per Fly app with `fly secrets set`. The full list is in
[`deploy/fly/README.md`](../../deploy/fly/README.md). Config that isn't secret (APP_ENV, retention,
MFA, logging, rate-limit toggles) lives in each app's `[env]` block.

### Supabase connection mode

Use the **session pooler** connection string (or a direct connection) for `DATABASE_URL` on all
apps and the release command. The **transaction pooler** breaks session advisory locks (workspace
provisioning, the concurrent-run guard) and per-connection `schema_translate_map`. The API's
startup readiness check takes and releases a `pg_advisory_lock` and refuses to boot if it can't —
so a mis-pointed URL fails fast and loudly rather than corrupting tenant isolation.

## First deploy

```bash
# apps (once)
fly apps create visionguard-api && fly apps create visionguard-worker && fly apps create visionguard-beat
# secrets on each app (see deploy/fly/README.md)
fly secrets set DATABASE_URL=… REDIS_URL=… CLERK_JWT_ISSUER=… … -a visionguard-api
#   … repeat for -worker and -beat
# deploy api first — its release_command runs migrations (public then every tenant schema); a
# non-zero exit aborts the deploy before the new version goes live
fly deploy -c deploy/fly/api.toml
fly deploy -c deploy/fly/worker.toml
fly deploy -c deploy/fly/beat.toml
fly scale count 1 -a visionguard-beat        # beat MUST be a single machine
```

Then run the smoke test (below). Subsequent deploys are just the three `fly deploy` commands;
migrations re-run idempotently.

## Migrations

Run **only** as the api app's `release_command` (`python -m api.app.cli migrate` → `upgrade_all`:
public first, then each tenant schema in `public.workspaces`). Never on app boot. A migration
failure fails the release and aborts the deploy. To run manually against an environment (e.g. a
restore drill): `fly ssh console -a visionguard-api -C "python -m api.app.cli migrate"`.

## Web (Vercel)

Project root `web/`; build command `npm run build`; output `dist`. Set `VITE_API_BASE_URL` and
`VITE_CLERK_PUBLISHABLE_KEY`. Security headers (CSP allowing only the API origin + Clerk, HSTS,
`frame-ancestors 'none'`) come from `web/vercel.json` — update the CSP `connect-src`/`script-src`
hosts to match the real API + Clerk domains.

**Never set `VITE_DEV_AUTH` in a Vercel (or any deployed) build.** It gates the dev-only
screenshot bypass (Slice 14) that skips Clerk sign-in and reads a token from `localStorage`. The
production build command is a plain `npm run build` (default mode), which does **not** load
`web/.env.capture` (that file is only read under `vite --mode capture`), so the flag is unset and
the bypass is dead-code-eliminated from `dist/`. CI enforces this: the frontend job greps the
built bundle and fails if any dev-auth string (`vg_dev_token`, `VITE_DEV_AUTH`, …) appears. Even
if the flag were somehow set, it only makes the SPA read a token string — the API still verifies
every token, and the backend `AUTH_TEST_MODE` bypass that would accept such a token refuses to
boot outside `APP_ENV` dev/test (`api/app/config.py` `_guard_test_mode`; tested in
`api/tests/test_auth_test_mode.py`).

## Backups, PITR & the restore drill

- **Backups / PITR:** enable Supabase **Pro** daily backups and **Point-in-Time Recovery**. Target
  RPO ≤ 5 min (PITR), RTO ≤ 1 h. Evidence immutability is a separate layer: R2 object lock (7-year
  retention in production) means sealed evidence survives even a full DB restore.
- **Restore drill (run quarterly; record the date below):**
  1. Restore the latest backup / PITR checkpoint into a **scratch** Supabase project.
  2. Point a throwaway api machine at it and run `python -m api.app.cli migrate` (should be a no-op
     if the backup is current).
  3. Run `scripts/smoke.py` against that machine — all steps must pass.
  4. Verify an existing evidence pack with `vg verify-evidence --workspace-id … --case-id …
     --capture-id …` (hashes + timestamp token still valid).
  5. Tear down the scratch project.
- **Last restore drill:** _not yet run — schedule after first production data exists._

## Rollback

`fly releases -a visionguard-api` then `fly deploy -c deploy/fly/api.toml --image <previous>` (or
`fly releases rollback`). Note: a rollback does **not** revert migrations — forward migrations must
be backward-compatible with the previous image (add-then-migrate, never destructive in the same
release). Roll worker/beat back the same way.

## Post-deploy smoke test

```bash
python scripts/smoke.py --base-url https://visionguard-api-staging.fly.dev --token "$STAFF_TOKEN"
```

`$STAFF_TOKEN` is an **admin** staff Clerk session token (needs all-workspaces access to create and
read a workspace). On staging you can mint one; in production copy a real staff session token. The
script asserts readiness → create workspace → agent authorization → subject → upload image → URL
intake → generate report, and exits non-zero on the first failure.

## Health checks

Fly routes traffic to the api only when `/readyz` is 200 (DB + Redis + storage reachable);
`/healthz` is liveness. If `/readyz` flaps, check the dependency booleans in its body (no secrets
are logged) and the app logs.
