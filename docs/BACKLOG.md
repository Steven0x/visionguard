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

> **Pre-production requirement (CSAM):** discovery ingests thumbnails of found content from the open web, which may include illegal imagery. Before production, every fetched image MUST pass PhotoDNA-style CSAM hash-scanning at the `add_image_candidate` choke point BEFORE it is stored or displayed; a positive match must be routed to the NCMEC report path and never stored/shown (CLAUDE.md #7). Slice 4 defers the scanner itself but is structured so it can be dropped in at one place. This must be closed before any real crawling.
> **Deferred:** Drive/folder URL pulls; matching/scoring of candidates (Slice 5). Slice 4 is provider-APIs + manual intake only. See `docs/specs/discovery.md`.

## Slice 5: Matching and the review inbox

- Score candidates: pHash distance → embedding similarity → rules (source type, risky keywords, allowlist)
- Inbox: side-by-side (original vs found), score, source, suggested claim type; keyboard shortcuts; bulk actions (by domain or account)
- Confirm → creates a case; Dismiss → reason (`not a match`, `licensed`, `fair use`, `own account`), which feeds training data
- Allowlist check before a candidate enters the inbox

**Done when:** a reviewer clears 100 candidates in under 15 minutes; every decision is stored as a labeled example.
**Agents:** reviewer

## Slice 6: Cases and the lifecycle

- Case service with an enforced state machine (see `CLAUDE.md`); every transition audited
- Case view: timeline, evidence, actions, outcome
- Group cases by offender (account, domain, seller) for bulk handling

**Done when:** illegal transitions are rejected by the service (tested); a case's full history can be exported.
**Agents:** reviewer, claims-checker

## Slice 7: Evidence capture

- On confirm: Playwright captures a full screenshot, raw HTML and a page archive; records URL, time, visible counts (views, followers, price)
- SHA-256 of each artifact; RFC 3161 timestamp from a trusted time-stamping authority; stored in the locked bucket
- Chain-of-custody log; export an evidence pack as a PDF

**Done when:** an evidence pack verifies (hashes match, timestamp token valid) using a standalone verify script; nothing in the evidence bucket can be overwritten.
**Agents:** reviewer, red-team

## Slice 8: Claims and the notice generator

- Claim selection per case, limited to what the subject's rights records support (claims matrix)
- Channel registry: platform → claim types → method (email, web form, portal) → required fields
- Notice templates per claim × channel (attorney-approved before use)
- Approval step: reviewer approves, the action records `approved_by`; email channels send via SendGrid; web-form channels produce a copy-ready packet and a checklist for staff to submit by hand
- Filing log per platform

**Done when:** a confirmed copyright case on an email-channel host goes out with one approval; a trademark case can't be routed to DMCA (tested); templates are marked `unapproved` until counsel signs off, and unapproved templates can't be sent.
**Agents:** reviewer, claims-checker, red-team (outbound)

## Slice 9: Outcomes and re-upload watch

- Record outcomes: removed, rejected, countered, no response; follow-up reminders after each platform's usual response window
- Automatic re-check of the URL: removed → `Removed`; still live → nudge for follow-up
- Removed cases move to `Monitoring`; matching new candidates reopen the case with its history attached

**Done when:** removal rate and median time to removal compute correctly per platform and claim type.
**Agents:** reviewer

## Slice 10: Reports and metrics

- Monthly report per workspace and per subject (PDF): found, removed, time to removal, open cases, highlights
- Internal metrics page: removal rate, median time to removal, review precision, wrong-filing rate, re-upload rate, review minutes per case, provider cost per workspace

**Done when:** the first agency report is generated from real data and sent; the metrics match a hand count on one workspace.
**Agents:** reviewer

---

## Explicitly deferred to Phase 2+

Customer portal and self-review, billing, liveness and ID verification, face matching (after consent flow v2 and counsel review), platform crawlers beyond provider APIs, automated web-form submission, recovery track (demand letters, CCB), Brands mode, white-label, EU/DSA.
