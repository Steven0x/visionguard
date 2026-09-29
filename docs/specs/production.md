# Production readiness (Slice 11)

How VisionGuard is made safe to deploy. Companion to the runbook in
[`docs/ops/deploy.md`](../ops/deploy.md) and [ADR 0014](../adr/0014-production-deploy.md). This
spec is the source of truth for the config guard, health contract, logging rules, and security
controls; the runbook is the operator procedure.

## Environments

`APP_ENV` selects behaviour: `dev` and `test` are local/CI (fakes allowed); `staging` and
`production` are **deployments** and get the strict guard below. `is_deployed` ≙
`APP_ENV ∈ {staging, production}`; `is_production` ≙ `APP_ENV == production`.

Staging is a real mirror of production running the **same container images**. The only deliberate
differences: `EMAIL_BACKEND=outbox` (staging can never send real mail) and a separate
`vg-evidence-staging` bucket at 1-day object-lock retention.

## The deployed-environment config guard

`Settings._guard_deployed_env` (in `api/app/config.py`) runs at load and **refuses to start** a
deployment when any of these hold. All failures are collected and reported together.

| Check | Requirement in a deployment |
| --- | --- |
| Embedder | `EMBEDDER_BACKEND=clip` (no fake) |
| Fetcher | `FETCHER_BACKEND=safe` |
| Provider | `PROVIDER_BACKEND=serpapi` |
| Capture | `CAPTURE_BACKEND=playwright` |
| TSA | `TSA_BACKEND=rfc3161` |
| Storage | `STORAGE_BACKEND=s3` |
| CSAM | `CSAM_SCANNER_BACKEND` ∈ real backends (never `none`/`fake`) |
| Clerk | `CLERK_JWT_ISSUER` and `CLERK_JWKS_URL` set |
| MFA | `CLERK_REQUIRE_MFA=true` |
| CORS | `ALLOWED_ORIGINS` non-empty, every entry an exact origin (`scheme://host[:port]`, no `*`, no path) |
| Email | production → `sendgrid` (+ creds); staging → `outbox` |
| Retention | production → `EVIDENCE_RETENTION_DAYS ≥ 2555` unless `EVIDENCE_RETENTION_OVERRIDE_REASON` set |

**Intentional consequence (CLAUDE.md #7):** no real CSAM scanner backend exists yet, so a
deployment cannot boot until one is connected. There is **no env var or flag** that relaxes this —
staging is held to the same bar. Production must not run with imagery flowing and no scanner.

Two further checks need the network and run at **startup**, not config load
(`verify_deployed_readiness`, in the FastAPI lifespan):

- **Evidence object lock** — the evidence bucket must report object lock enabled, else boot aborts
  (evidence is write-once, CLAUDE.md #6).
- **Session advisory locks** — the DB connection must hold a session-level advisory lock across two
  statements. A Supabase *transaction* pooler can't, so this catches a mis-pointed `DATABASE_URL`
  (use the session pooler or a direct connection).

## Health & readiness

- `GET /healthz` — liveness. Process is up; no dependency checks. Platform uses it to decide
  whether to restart the machine.
- `GET /readyz` — readiness. Checks DB (`SELECT 1`), Redis (`PING`), and storage (`head_bucket` on
  both buckets). Returns `200 {"status":"ok","checks":{…}}` or `503`. The body carries only
  per-dependency booleans — no hosts, URLs, or secrets. The result is **cached ~5s** so the probe
  can't be used to hammer the backends.

## Logging & scrubbing

Structured JSON to stdout in deployments (`LOG_JSON=true`). A `ScrubbingFilter`
(`api/app/obs/logging.py`) rewrites every record and redacts:

- bearer tokens and JWTs,
- email addresses,
- URL paths and query strings — only `scheme://host` survives (this is what keeps **URLs of ncii
  cases** out of logs; a leak/candidate URL never persists as a full string).

The filter is also attached to the `uvicorn`/`gunicorn` access + error loggers, so request lines
(which include the path+query) are scrubbed too.

**Rule (enforced by review):** never pass file bytes or request/response bodies to the logger.

## Error tracking

Sentry, initialised only when `SENTRY_DSN` is set (`api/app/obs/sentry.py`; `[obs]` extra). Its
`before_send` runs the same scrubber over the event message, request URL, and headers, so no
tokens/emails/ncii URLs/file contents leave the process. `send_default_pii=False`.

## Security controls

The request-size limit is **always on** (a cheap global backstop above the finer per-upload caps).
Security headers, rate limiting, MFA, and JSON logging are **off by default** (dev/test unchanged)
but **required in deployments** — the config guard refuses to boot a staging/production env that
has any of them off, so a deployment can never silently run degraded.

- **Request size limit** (`MAX_REQUEST_BYTES`, default 30 MB): **always on**. Enforced on **bytes
  actually received** — streamed chunks are counted, so a lying/absent `Content-Length` (e.g.
  chunked transfer) can't slip a huge body past. A declared length over the limit is rejected up
  front. Per-upload caps (assets, documents) remain the finer limit.
- **Security headers** (`SECURITY_HEADERS_ENABLED`): `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`,
  `Cross-Origin-Opener-Policy: same-origin`, and HSTS in production.
- **Rate limiting** (`RATE_LIMIT_ENABLED`, `RATE_LIMIT_WRITES_PER_MIN`): a Redis fixed-window
  counter on mutating methods, keyed on the **verified `staff.id`**. Unauthenticated writers are
  keyed on the client IP taken **only** from `Fly-Client-IP` (never `X-Forwarded-For`). A forged
  token is rejected at verification and keyed on IP, so it can neither reset nor borrow a real
  staff member's quota. Fails open on a Redis blip.
- **MFA** (`CLERK_REQUIRE_MFA`): enforced server-side by checking Clerk's `fva` (factor
  verification age) session claim — a session without a verified second factor is rejected. Not
  just a Clerk dashboard setting.
- **Web** carries its own CSP/HSTS via `web/vercel.json` (CSP allows only the API origin + Clerk;
  `frame-ancestors 'none'`).

## Containers & deploy

Digest-pinned, non-root, slim images: `docker/api.Dockerfile` (uvicorn),
`docker/worker.Dockerfile` (heavy — torch + Playwright/Chromium), `docker/beat.Dockerfile`
(light). Web builds as a static site on Vercel. Migrations run as a **release step**
(`release_command`), never on boot. Beat runs as exactly one machine; scheduled tasks also take a
per-job Redis lock (`worker/locks.py`) so a stray second beat is a no-op. Full topology, secrets,
and procedure in [`docs/ops/deploy.md`](../ops/deploy.md).

## Post-deploy smoke test

`scripts/smoke.py --base-url … --token …` runs the core path against a live deployment: readiness →
create workspace → add an agent authorization → add a subject → upload one image → run a manual URL
intake → generate a report. Exits non-zero on the first failure; never prints the token.

## Tests

`api/tests/test_production_guard.py` (every refusal + a valid config), `test_startup_readiness.py`,
`test_readyz.py`, `test_log_scrubber.py`, `test_mfa.py`, `test_security_middleware.py`, and
`worker/tests/test_beat_lock.py`. The suite runs with the middleware/limits **disabled by default**,
so dev/test behaviour is unchanged.
