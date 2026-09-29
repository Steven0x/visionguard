# ADR 0014: Production readiness & deploy (Slice 11)

Status: accepted (2026-09-29)

## Context

Phase 1 is code-complete and runs locally with every external backend defaulting to a fake/none
implementation, so CI and dev never touch real infrastructure, money, or the open web. Slice 11
makes VisionGuard *deployable*: it must be impossible to accidentally ship a deployment that is
degraded (fake backends, missing auth, unlocked evidence), and operators need containers, a real
migration release step, health probes, scrubbed logs, security controls, backups, error tracking,
a staging mirror, and a smoke test.

## Decisions

### 1. A deployed environment refuses to boot unless it is fully production-safe

A new `_guard_deployed_env` validator in `api/app/config.py` fires when `APP_ENV` is `staging` or
`production` and raises (aborting boot) if **any** pluggable backend is fake/none (embedder,
fetcher, provider, capture, TSA, storage, CSAM), if Clerk isn't configured, if CORS isn't a
non-empty list of exact origins, if MFA isn't required, or (production) if evidence retention is
below the 7-year floor without a documented override. All problems are reported at once.

Consequence, by design: because **no real CSAM scanner backend exists yet** (`_REAL_CSAM_BACKENDS`
is empty), a deployment cannot boot until one is connected (CLAUDE.md #7). There is **no env var or
flag** that relaxes this — staging is a real mirror and is held to the same bar. The evidence
bucket's object lock and the DB's session-advisory-lock support are verified at *startup*
(`verify_deployed_readiness`), not in the settings validator, since they need the network.

### 2. Staging = production images, fake email only

Staging runs the same containers as production. The single deliberate difference is
`EMAIL_BACKEND=outbox` (staging can never send real mail) plus a separate `vg-evidence-staging`
bucket at 1-day object-lock retention so test captures aren't immutable for 7 years. Everything
else — real storage, capture, providers, Clerk, MFA, the CSAM requirement — matches production.

### 3. Hosting: Fly.io for compute, dedicated Redis, the pinned data plane elsewhere

API / worker / beat run on Fly.io from our own digest-pinned, non-root, slim Dockerfiles (worker is
a separate heavier image carrying torch + Playwright). The data plane stays on the CLAUDE.md stack:
Supabase Postgres + pgvector, Cloudflare R2, Vercel static web, Clerk. The Celery broker is a
**dedicated managed Redis**, not Upstash serverless — Celery long-polls the broker constantly, which
suits a persistent instance rather than a per-command-billed serverless one. Supabase must be
reached via the **session pooler or a direct connection, never the transaction pooler** (which
breaks session advisory locks and per-connection schema settings); the startup readiness check
enforces this.

### 4. Migrations are a release step, never a boot step

The api Fly app's `release_command` runs `python -m api.app.cli migrate` (public then every tenant
schema) on the new image before traffic cuts over; a non-zero exit aborts the deploy. App startup
(the FastAPI lifespan) never migrates.

### 5. Structured, scrubbed logs everywhere; Sentry behind a flag

`api/app/obs/logging.py` installs a JSON formatter plus a `ScrubbingFilter` that redacts bearer
tokens, JWTs, emails, and URL paths/queries (only `scheme://host` survives — this is how "URLs of
ncii cases" stay out of logs). The filter is also attached to the uvicorn/gunicorn access + error
loggers. Error tracking is Sentry (`api/app/obs/sentry.py`), a no-op unless `SENTRY_DSN` is set, with
a `before_send` hook that runs the same scrubber so nothing sensitive leaves the process.

### 6. Security controls, off in dev/test and on in deployments

Security headers, a request-size limit enforced on **bytes actually received** (not just
`Content-Length`, so a chunked body can't slip past), and rate limiting on authed writes keyed on
the **verified `staff.id`** (unauthenticated writers on the `Fly-Client-IP` header only, never
`X-Forwarded-For`) — a forged token is rejected at verification and can neither reset nor borrow a
real staff member's quota. MFA is enforced server-side by checking Clerk's `fva` session claim, not
just a dashboard setting. The web app carries its own CSP/HSTS via `web/vercel.json`.

### 7. Beat runs as exactly one machine, with a lock as backstop

`fly scale count 1` pins beat to one instance; additionally every scheduled task takes a per-job
Redis lock (`worker/locks.py`, fails open) so a stray second beat is a no-op rather than a
double-dispatch.

### 8. Evidence retention default = 7 years (2555 days), config-driven

Production defaults to 2555-day object-lock retention (the claims-matrix open item, pending
counsel), enforced as a floor by the config guard and overridable only with a documented reason.
Staging uses 1 day.

## Alternatives considered

- **Render / Railway** instead of Fly — simpler managed PaaS, but we're already writing Dockerfiles
  and want a real pre-deploy migration release step and non-root images; Fly's `release_command`
  and per-app images fit best.
- **Upstash serverless Redis** (the CLAUDE.md-named option) — works with Celery but bills per
  command and has connection limits; the constant broker polling makes a dedicated instance the
  better fit. Revisit if volume stays tiny.
- **Allowing a fake CSAM scanner in staging** so staging is usable before the real scanner lands —
  rejected: it would create exactly the bypass CLAUDE.md #7 forbids. Staging stays blocked until the
  scanner is connected.

## Consequences

- Neither staging nor production can boot until a real CSAM scanner backend is implemented behind
  the `csam.py` interface. This is the intended gate on going live with imagery.
- The migration-on-boot path is gone; deploys depend on the release command succeeding.
