# Fly.io deployment

Three apps per environment share the codebase but use different images:

| App | Image | Role |
| --- | --- | --- |
| `visionguard-api` | `docker/api.Dockerfile` | FastAPI (HTTP), runs the migration release step |
| `visionguard-worker` | `docker/worker.Dockerfile` | Celery worker (torch + Playwright) |
| `visionguard-beat` | `docker/beat.Dockerfile` | Celery beat scheduler — **exactly one machine** |

Staging mirrors these with `-staging` suffixes and the `*.staging.toml` configs (same images,
`APP_ENV=staging`, **fake email only**, a separate `vg-evidence-staging` bucket at 1-day retention).

The full runbook — backups/PITR, restore drill, rollback, smoke test — is in
[`docs/ops/deploy.md`](../../docs/ops/deploy.md). This file is the quick reference.

## Secrets (never commit these)

Set per app with `fly secrets set KEY=value -a <app>`. All three apps in an environment need the
same values:

```
DATABASE_URL              # Supabase SESSION pooler or direct — NOT the transaction pooler (see below)
REDIS_URL                 # dedicated managed Redis (rediss://…), works well with Celery polling
CLERK_JWT_ISSUER
CLERK_JWKS_URL
CLERK_AUDIENCE            # optional
ALLOWED_ORIGINS           # exact origins only, comma-separated, e.g. https://app.visionguard.com
STORAGE_ENDPOINT_URL      # https://<account>.r2.cloudflarestorage.com
STORAGE_ACCESS_KEY_ID
STORAGE_SECRET_ACCESS_KEY
STORAGE_BUCKET            # vg-assets
STORAGE_EVIDENCE_BUCKET   # vg-evidence (prod) — object lock enabled at creation
SERPAPI_KEY
TINEYE_API_KEY            # optional
SENDGRID_API_KEY          # production only (staging uses the outbox)
EMAIL_FROM
SENTRY_DSN                # optional; error tracking is off if unset
CSAM_SCANNER_BACKEND      # a REAL scanner name — until one exists, deploys refuse to boot (intended)
```

Non-secret config (APP_ENV, LOG_JSON, retention, MFA, rate limiting, etc.) lives in the `[env]`
block of each toml.

## Supabase connection mode (important)

Use the **session pooler** connection string (or a direct connection) for `DATABASE_URL` on all
three apps **and** the migration release command. The **transaction pooler** multiplexes
connections per statement, which breaks session-level advisory locks (workspace provisioning, the
concurrent-run guard) and per-connection `schema_translate_map` settings. The API verifies this at
startup (`verify_deployed_readiness`) and refuses to boot if the connection can't hold a session
advisory lock.

## First deploy (per environment)

```bash
# 1. Create the apps (once)
fly apps create visionguard-api
fly apps create visionguard-worker
fly apps create visionguard-beat

# 2. Set secrets on each app (see above)
fly secrets set DATABASE_URL=… REDIS_URL=… … -a visionguard-api
#   … repeat for -worker and -beat

# 3. Deploy the API first (its release_command runs migrations: public then every tenant schema;
#    a failure aborts the deploy and no new version goes live)
fly deploy -c deploy/fly/api.toml

# 4. Deploy worker and beat
fly deploy -c deploy/fly/worker.toml
fly deploy -c deploy/fly/beat.toml

# 5. Pin beat to a single machine
fly scale count 1 -a visionguard-beat
```

Subsequent deploys are just steps 3–4 (migrations re-run idempotently from the api release step).

## Notes

- The api app's health check hits `/readyz`; Fly only routes traffic when DB + Redis + storage are
  reachable. `/healthz` is liveness.
- Until a real CSAM scanner backend is connected, **production and staging will refuse to boot**
  (config guard). This is intentional (CLAUDE.md #7).
