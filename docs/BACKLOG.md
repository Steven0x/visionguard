# Phase 1 backlog: the internal concierge tool

**Goal:** VisionGuard staff can take an agency from onboarding to filed, tracked takedowns with sealed evidence, and cut review time per case every week.
**Users:** VisionGuard staff only. No customer logins in Phase 1; customers get reports.
**Exit test (from the product outline):** 5–10 paying agencies, review cost per case falling, customers renewing after month 3.

Build in this order. Each slice is a vertical cut (UI → API → DB → worker) and ships on its own. Don't start a slice until the one before it passes its acceptance criteria and the review agents.

---

## Slice 0: Scaffold and foundations

- Monorepo: `api/` (FastAPI), `worker/` (Celery), `web/` (React + Vite), `docs/`, `templates/`
- Clerk auth for staff; role column: `admin`, `reviewer`
- Postgres schema-per-tenant with a tenant router; Alembic migrations run across all schemas
- R2 buckets: `assets` (normal) and `evidence` (object lock enabled)
- CI: lint, typecheck, tests on every push; `.env.example`
- Audit log table + helper (who, what, when, workspace, entity)

**Done when:** `make dev` runs everything locally; CI is green; a test proves a query in workspace A can't read workspace B.
**Agents:** reviewer, red-team

**Follow-up (DB role):** The app must connect as a non-owner DB role (e.g. `vg_app`) so the `audit_log` REVOKE is actually enforced; migrations run as the owner role. Today the app connects as the owner, so the REVOKE is not yet effective.

## Slice 1: Workspaces and subjects

- Create and edit an agency workspace (name, contact, plan, allowlist)
- Add subjects (people): name, stage names, handles, residence state, notes
- Residence in IL or WA sets `biometrics_blocked = true`

**Done when:** staff can create a workspace with 20 subjects in under 10 minutes (CSV import); isolation tests pass.
**Agents:** reviewer, red-team

## Slice 2: Rights and consent records

- Upload rights documents per subject: management agreement, photographer license, registrations
- Consent records: type (`enforcement`, `biometric`), signed PDF, date, signer; revoke action
- Agent-authorization record: VisionGuard is authorized to act for this subject or workspace
- Phase 1 consent is a signed PDF + staff attestation. Phase 2 adds liveness and ID verification.

**Done when:** a subject shows which claim types are currently supported (from the claims matrix); revoking biometric consent deletes templates (tested, even though templates don't exist yet: build the hook now).
**Agents:** reviewer, red-team, claims-checker

## Slice 3: Assets and fingerprints

- Upload photos and videos (extract frames) per subject; pull from a folder or Drive link
- Worker computes a pHash and an OpenCLIP embedding for each asset → pgvector
- Text identifiers per subject: names, handles, keywords (e.g. "leaked", stage name + platform)

**Done when:** 500 images upload and are fingerprinted in the background; duplicate uploads are detected by hash.
**Agents:** reviewer, red-team (uploads)

> **Deferred:** video upload + frame extraction, and Drive/folder pulls, are deferred to a later slice. Slice 3 is **images only** (JPEG/PNG/WebP). See `docs/specs/assets.md`.

## Slice 4: Discovery v1

- **Manual URL intake:** paste one or many URLs (from staff, talent or fans) → fetch → candidate matches. SSRF-safe fetcher.
- **Reverse image jobs:** for each asset, query SerpApi Google Lens and TinEye on a schedule; store results as candidates with their source
- **Keyword jobs:** search engine queries for name and handle + risky terms
- Per-workspace scan budget and frequency

**Done when:** a scheduled run for one workspace produces candidates with source, thumbnail and URL; provider costs are logged per workspace.
**Agents:** reviewer, red-team (SSRF, fetcher)

> **Pre-production requirement (CSAM):** discovery ingests thumbnails of found content from the open web, which may include illegal imagery. Before production, every fetched image MUST pass PhotoDNA-style CSAM hash-scanning at the `add_image_candidate` choke point BEFORE it is stored or displayed; a positive match must be routed to the NCMEC report path and never stored/shown (CLAUDE.md #7). Slice 4 defers the scanner itself but is structured so it can be dropped in at one place. This must be closed before any real crawling. **Update (Slice 7):** the per-image `CsamScanner` gate is now wired here and everywhere else imagery is stored — only the real scanner backend remains (ADR 0010).
> **Deferred:** Drive/folder URL pulls; matching/scoring of candidates (Slice 5). Slice 4 is provider-APIs + manual intake only. See `docs/specs/discovery.md`.

## Slice 5: Matching and the review inbox

- Score candidates: pHash distance → embedding similarity → rules (source type, risky keywords, allowlist)
- Inbox: side-by-side (original vs found), score, source, suggested claim type; keyboard shortcuts; bulk actions (by domain or account)
- Confirm → creates a case; Dismiss → reason (`not a match`, `licensed`, `fair use`, `own account`), which feeds training data
- Allowlist check before a candidate enters the inbox

**Done when:** a reviewer clears 100 candidates in under 15 minutes; every decision is stored as a labeled example.
**Agents:** reviewer

> **Deferred:** the case state machine / timeline / offender-grouping (Slice 6), evidence
> capture (Slice 7) and notice generation (Slice 8). Slice 5 ships a **case stub** (status
> `Confirmed`) and only **stores** labeled decisions — the XGBoost classifier that consumes
> them is later. "Match" is represented by a scored discovery candidate (no separate table).
> See `docs/specs/review.md`.

## Slice 6: Cases and the lifecycle

- Case service with an enforced state machine (see `CLAUDE.md`); every transition audited
- Case view: timeline, evidence, actions, outcome
- Group cases by offender (account, domain, seller) for bulk handling

**Done when:** illegal transitions are rejected by the service (tested); a case's full history can be exported.
**Agents:** reviewer, claims-checker

> **Amended state machine (see `docs/specs/cases.md`, ADR 0008):** added terminal `Withdrawn`
> (`Filed → Withdrawn`, note required) to correct a wrong claim by re-filing a *new* case from
> the same candidate (linked, both timelines); `Countered` is non-terminal
> (`Countered → Escalated | Closed`). Removal metrics count only real `Removed` transitions.
> **Deferred:** `requires_evidence_pack()` is a placeholder returning `True` (Slice 7 fills it);
> auto-reopen on reappearance + timer firing/notifications + metrics computation are Slices 9–10.

## Slice 7: Evidence capture

- On confirm: Playwright captures a full screenshot, raw HTML and a page archive; records URL, time, visible counts (views, followers, price)
- SHA-256 of each artifact; RFC 3161 timestamp from a trusted time-stamping authority; stored in the locked bucket
- Chain-of-custody log; export an evidence pack as a PDF

**Done when:** an evidence pack verifies (hashes match, timestamp token valid) using a standalone verify script; nothing in the evidence bucket can be overwritten.
**Agents:** reviewer, red-team

> **CSAM (interface DONE; real backend pre-production):** a per-image `CsamScanner` gate
> (`api/app/csam.py`, ADR 0010) now runs at EVERY point open-web/uploaded imagery is stored —
> discovery `add_image_candidate`, evidence capture (browser egress + screenshot), manual
> evidence upload, and Slice-3 asset upload. Nothing is stored/sealed without a `clean` result;
> a match records a minimized `csam_incidents` row (hash/URL/time only) in an admin-only
> escalation queue; `none` (default) and errors fail closed. The remaining pre-production task
> is the real PhotoDNA/Safer backend behind the same interface. See `docs/specs/evidence.md`,
> ADR 0009 + 0010.
> **Delivered:** SSRF-safe browser egress (fetch-through-SafeFetcher + fulfill, no DNS rebind),
> write-once object-locked evidence bucket, RFC 3161 timestamping (+ untimestamped retry beat),
> chain-of-custody, `requires_evidence_pack()` filled (fresh sealed capture gates Filed),
> admin-only PDF pack (reason + sensitive-opt-in logged), and a standalone `vg verify-evidence`.

## Slice 8: Claims and the notice generator

- Claim selection per case, limited to what the subject's rights records support (claims matrix)
- Channel registry: platform → claim types → method (email, web form, portal) → required fields
- Notice templates per claim × channel (attorney-approved before use)
- Approval step: reviewer approves, the action records `approved_by`; email channels send via SendGrid; web-form channels produce a copy-ready packet and a checklist for staff to submit by hand
- Filing log per platform

**Done when:** a confirmed copyright case on an email-channel host goes out with one approval; a trademark case can't be routed to DMCA (tested); templates are marked `unapproved` until counsel signs off, and unapproved templates can't be sent.
**Agents:** reviewer, claims-checker, red-team (outbound)

> **Delivered:** global (public-schema) channel registry + notice templates (matrix-conformant
> seed; `trademark`/`likeness` can never route to DMCA/email — tested), draft→edit→approve→send
> flow with a **send-time re-check** (active auth + supported claim + fresh sealed evidence +
> counsel-approved template + recorded human approval, all in one transaction), safe minimal
> renderer with CR/LF header/recipient injection guards, SendGrid + **outbox** email (dev/test
> can never send real mail), the exact sent notice sealed write-once via `CaptureKind.notice`
> (reusing Slice-7 sealing), web-form/portal copy-ready packet + hand-submission (CSAM-scanned,
> sealed screenshot + ticket), filing log, and `Filed → Withdrawn` retraction. Templates ship
> `unapproved`, so **nothing can be sent until counsel signs off — intended**. See
> `docs/specs/notices.md`, ADR 0011.
> **Deferred:** identity verification (Phase 2) still gates a real `likeness`/`ncii`/
> `impersonation` send; `trademark` needs a Brands-mode registration record; outcomes/re-check
> (Slice 9); automated web-form submission and demand letters (Phase 2+).

## Slice 9: Outcomes and re-upload watch

- Record outcomes: removed, rejected, countered, no response; follow-up reminders after each platform's usual response window
- Automatic re-check of the URL: removed → `Removed`; still live → nudge for follow-up
- Removed cases move to `Monitoring`; matching new candidates reopen the case with its history attached

**Done when:** removal rate and median time to removal compute correctly per platform and claim type.
**Agents:** reviewer, red-team (SafeFetcher.probe + reopen guards)

> **Delivered:** `notice_outcomes` (append-only, corrections supersede) map outcomes onto the
> existing machine (`removed`→Removed, `countered`→Countered; `rejected`/`no_response` stay Filed
> and reset the follow-up timer). Per-platform `channels.response_window_days` drives follow-up
> due dates + an overdue-filed **follow-ups** list. A daily SafeFetcher **`probe`** (status-only,
> **never downloads the body**; SSRF-hardened) records `url_rechecks` and only *proposes* — a
> removal on two `gone`s ≥24h apart, a reappearance only on `gone→live` — a human confirms
> (sealing the removal proof via Slice 7). The `removed→monitoring→closed` tail auto-advances on a
> beat. A reappearance (same URL / platform account / non-platform host+asset — **never
> domain-merged on a platform**) **reopens** the monitoring case with its history instead of
> duplicating; reopen re-checks consent + allowlist + claim and needs a **fresh approval**.
> Removal-rate + median time-to-removal (per platform × claim, **per filing**, `effective_at`
> based, tested against a hand-computed fixture with a reopened + a withdrawn case) in
> `services/metrics.py` + `GET /metrics/removals`. See `docs/specs/outcomes.md`, ADR 0012.
> **Deferred:** the polished internal metrics page + monthly customer reports (Slice 10);
> automated re-filing; recovery/demand letters (Phase 2+).

## Slice 10: Reports and metrics

- Monthly report per workspace and per subject (PDF): found, removed, time to removal, open cases, highlights
- Internal metrics page: removal rate, median time to removal, review precision, wrong-filing rate, re-upload rate, review minutes per case, provider cost per workspace

**Done when:** the first agency report is generated from real data and sent; the metrics match a hand count on one workspace.
**Agents:** reviewer

> **Delivered:** `services/metrics.py` is the **single source of counting** — `report_metrics`
> (agency funnel: found / filed / removed split verified-vs-staff-only / median time-to-removal /
> still-pending / open-cases-by-status / "Needs from you", all per-filing, `subject_id`- and
> date-range-scoped) and `metrics_summary` (removal rate, median TTR, review precision,
> wrong-filing rate, re-upload rate, review minutes per case, provider cost per workspace) —
> each formula written next to its definition in `docs/specs/reports.md`; the report layer does
> no counting (tested: report totals == metrics totals). Agency **PDF** + a **JSON input
> snapshot** are computed "as of" a timestamp, SHA-256'd and **sealed write-once** in the
> object-locked evidence bucket; the append-only `reports` row stores the keys + hashes, so a
> report regenerates and `verify_report` re-checks it. **Data minimization:** ncii → no images
> ever + domain-only URLs; other-claim thumbnails off by default (per-report toggle); a
> per-subject report never includes another subject's data (each tested). Nothing is sent
> automatically — staff generate/review/download; generation + download are audited. Added
> `discovery_candidates.shown_at` (stamped once on first inbox render) so review-minutes measures
> shown→decision. See `docs/specs/reports.md`, ADR 0013.
> **Deferred (Phase 2+):** automated sending/scheduling; customer portal; cross-workspace
> roll-ups; recovery/demand letters.

## Slice 11: Production readiness & deploy

- Deployed-env config guard: `staging`/`production` refuse to boot if any backend is fake/none, if
  Clerk/CORS/MFA aren't set correctly, or (startup) if the evidence bucket's object lock or session
  advisory locks can't be verified
- Containers (non-root, pinned, slim) for api/worker/beat; web builds static on Vercel
- Migrations as a separate release step (never on boot); `/healthz` + `/readyz`; structured JSON
  logs with a scrubber (tokens, emails, ncii URLs, file contents)
- Security: headers, request-size limit on received bytes, rate limiting keyed on verified staff
  id, server-side Clerk MFA
- Backups/PITR + a documented restore drill; evidence retention default 7 years (config)
- Sentry behind a flag with the same scrubbing; a staging mirror (fake email only); a post-deploy
  smoke script

**Done when:** the guard refuses every degraded config (tested); images build and run non-root; the
smoke script passes against a running env.
**Agents:** reviewer, red-team

> **Delivered:** `_guard_deployed_env` (config.py) + startup `verify_deployed_readiness` (object
> lock + Supabase session-pooler advisory-lock check); `api/app/obs/` (scrubbed JSON logging routed
> through the uvicorn/gunicorn loggers, flagged Sentry, cached `/readyz`); `api/app/middleware/`
> (security headers, received-bytes size limit); rate limiting in the auth dependency; Clerk `fva`
> MFA; `worker/locks.py` beat single-run lock; `docker/*` + `deploy/fly/*` + `web/vercel.json`;
> `scripts/smoke.py`. See `docs/specs/production.md`, `docs/ops/deploy.md`, ADR 0014.
> **Intentional gate:** staging + production cannot boot until a REAL CSAM scanner backend is
> connected (CLAUDE.md #7) — no flag relaxes it. That is the remaining pre-production task.

## Slice 12: Agency portal (first Phase-2 capability, pulled forward)

- Invite-only agency users (new `agency` role), created by staff, bound to exactly one workspace;
  MFA required; revocation effective on the next request
- Read: their subjects, case list + statuses, case timeline (public-safe), reports (PDF download),
  and the "Needs from you" list
- Write (limited): submit a URL tip (→ manual intake candidate, staff-reviewed, never
  auto-confirmed) and answer a "Needs from you" item (text or PDF, → staff review)
- Default-deny: every staff route rejects agency (route-walk test); workspace from membership never
  the URL (IDOR tests); minimized responses (no images for sensitive/ncii, domain-only URLs, no
  evidence files/notes/reviewer names/costs/metrics); every action + report download audited
- Outsider PDF uploads: embedded images CSAM-scanned (fail closed), files quarantined; per-user
  daily tip cap; agency rows excluded from every staff-facing list

**Done when:** the default-deny walk + minimization + IDOR + new-table isolation tests pass; an
agency user sees only the portal (not the staff console) and can tip/answer/download.
**Agents:** reviewer, red-team

> **Delivered:** `agency` role on `Staff` + `get_agency_context`/`get_agency_session`
> (membership-resolved workspace, revocation on next request); `routers/portal.py` +
> `services/portal.py` (minimized reads, tip + needs-answer writes); `portal_submissions`
> (`0020_tenant`, isolation test) + staff review endpoints; admin agency-user management; outsider
> PDF embedded-image CSAM scan (`pypdf`, `CsamSource.portal_upload`, quarantine prefix); daily tip
> cap; agency excluded from assignee/approver/staff lists; role-routed web portal. See
> `docs/specs/portal.md`, ADR 0015.

---

## Explicitly deferred to Phase 2+

Agency self-signup/billing, liveness and ID verification, face matching (after consent flow v2 and counsel review), platform crawlers beyond provider APIs, automated web-form submission, recovery track (demand letters, CCB), Brands mode, white-label, EU/DSA.
