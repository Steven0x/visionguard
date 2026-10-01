# Spec: Agency portal (Slice 12)

Status: draft. First Phase-2 capability pulled forward. A narrow, **invite-only** customer portal
that lets a paying agency self-serve the read-only picture of its enforcement and take two
tightly-scoped write actions — without ever touching the staff enforcement machine.

Non-negotiables in play:
- **#2 no open surface.** The portal exposes only the agency's own workspace; the workspace is
  resolved from the user's membership, **never** from a URL/body parameter.
- **#3 human in the loop.** Agency writes create *staff work* (a pending candidate; a submission to
  review). Agencies can never confirm, dismiss, file, approve, or withdraw.
- **#5 tenant isolation.** One agency = one workspace = one tenant schema. The new
  `portal_submissions` table is tenant-scoped with an isolation test.
- **#6 evidence immutable.** The portal serves the already-sealed report PDF; it never writes to
  evidence.
- **#7 minimize sensitive data.** Every portal response is minimized (below). Outsider-uploaded
  PDFs are CSAM-scanned (embedded images too) and quarantined.

See ADR `docs/adr/0015-agency-portal.md`.

## Identity, membership, revocation

An agency user is a row in the existing **`Staff`** table with the new role **`agency`**
(`StaffRole.agency`; `role` is a `String(20)` column, so no enum DDL). It has
`all_workspaces = False` and **exactly one** `StaffWorkspaceAccess` grant — its workspace. MFA is
required exactly as for staff (the global `clerk_require_mfa` + `fva` check in `verify_token`).

Two new dependencies in `api/app/auth/deps.py`:
- `get_agency_context` → 403 unless `role == agency`, `not all_workspaces`, and **exactly one**
  access grant; returns the `Workspace` resolved from that grant. The grant is read from
  `public_session` on **every request**, so deleting it revokes access on the **next** call
  (not just at token expiry).
- `get_agency_session` → opens a `tenant_session` bound to that workspace's schema. Portal routes
  carry **no** `workspace_id`/`subject_id` path chooser that crosses tenants, so cross-agency IDOR
  is structurally impossible: an agency can only ever address its own schema.

### Admin management (staff-only, `require_role(admin)`)
- `POST /workspaces/{id}/agency-users` `{clerk_user_id, email}` → create `Staff(role=agency,
  all_workspaces=False)` + one grant to `{id}`; reject if that Clerk user already has any grant
  (enforces one-workspace). Audited `agency_user.created`.
- `GET /workspaces/{id}/agency-users` → list this workspace's agency users.
- `DELETE /workspaces/{id}/agency-users/{staff_id}` → revoke (delete the grant). Audited
  `agency_user.revoked`.

## Default-deny

Every existing staff route rejects `agency` — role-gated routes already do (agency ∉
`{admin, reviewer}` → 403). The only non-role-gated staff routes are `me.py`: `GET /me` stays open
(the portal reads its own identity there) and `PUT /me/review-prefs` gains
`require_role(admin, reviewer)` so agency gets 403. A **guardrail test** walks every registered
route with an agency token and asserts 403, allowlisting only `/portal/*`, `GET /me`, and the
unauth health routes — so any future staff route that forgets its gate fails CI.

Agency users are excluded from every **staff-facing list**: `cases.assign` rejects an assignee
whose `Staff.role == agency`; approver/reviewer pickers and staff-admin listings filter out
`agency`. An agency user can never be assigned to a case or recorded as an approver.

## Portal surface — `/portal`, dep `get_agency_session`

All reads return **portal-safe** models. Writes are the only two, and never auto-confirm.

### Reads
- `GET /portal/context` → `{email, role, workspace: {id, name}}`.
- `GET /portal/subjects` → `[{id, legal_name, stage_names, handles, status}]` (drops `notes`,
  `biometrics_blocked`).
- `GET /portal/cases` → `[PortalCase]`; `GET /portal/cases/{case_id}` → `{case, timeline}`.
  `PortalCase = {id, subject_id, claim_type, status, display_url, created_at, updated_at}`.
  Timeline = **transitions only**: `[{from_status, to_status, created_at}]` from
  `CaseEvent.kind == transition`. Excluded everywhere: `offender_key`, `page_url`,
  `assigned_staff_id`, `opened_by_staff_id`, proposal/verify timestamps, `source_key`,
  `actor_staff_id`, event `reason`/`note`, and all `CaseNote`s.
- `GET /portal/reports` → `[{id, subject_id, period_start, period_end, created_at}]` (drops
  `generated_by_staff_id`, keys, hashes). `GET /portal/reports/{rid}.pdf` streams the sealed PDF
  (`reports.read_artifact("pdf")`); audited `report.downloaded`. No `inputs.json` route.
- `GET /portal/needs` → items derived from `metrics._needs_from_you`, scoped to the workspace: one
  per `(subject_id, need_type)` for `missing_authorization | ownership_rights |
  enforcement_consent`, each `{subject_id, subject_name, need_type, label}`.

### `display_url` rule (minimization)
`display_url` is **domain-only** (scheme + host, no path/query) when the case is `ncii` **or**
`sensitive`; the full `source_url` otherwise. **No image reference is ever returned** for any case,
sensitive or not. (Domain-only lets an agency tell sensitive cases apart without leaking the path.)

### Writes
- `POST /portal/tips` `{subject_id, url}` → validate the subject is in the tenant; enforce the
  **daily tip cap** (`portal_tip_daily_cap`, default 50, per agency user, counted from
  `portal_submissions` today) → **429** over the cap; record a `portal_submissions` row
  (kind=`url_tip`); call `discovery.intake_urls(subject, [url], actor_staff_id=agency.id)` (reuses
  SSRF-safe canonicalize + dedup; creates a `manual`/`link` candidate at `review_status=pending` →
  staff review inbox, never auto-confirmed). If the subject isn't enforceable
  (`DiscoveryNotAuthorized`) the submission is still recorded (staff see the tip) and the response
  says so. Audited `portal.tip_submitted`.
- `POST /portal/needs/answer` (multipart) `{subject_id, need_type, body?}` + optional PDF `file` →
  validate the subject; `need_type` must be one of the three buckets above; require text or a
  file. A file must be a PDF (`require_document_type` magic-byte sniff, 15 MB cap).
  **Outsider-PDF scanning:** extract the embedded images `pypdf` can enumerate and run each through
  `csam.scan_image`; a `match` records a `CsamIncident` (`CsamSource.portal_upload`), and a scan
  `error` or an unparseable PDF also fails closed — both store **no bytes** and return **422**. An
  accepted PDF is stored under a **quarantine prefix**
  (`{schema}/quarantine/needs_response/{uuid}.pdf`) that nothing renders inline — staff download
  only (so an image an extractor misses still can't auto-render). Record a `portal_submissions`
  row (kind=`needs_response`). Audited `portal.needs_answered`.

## Staff review of submissions (staff router, `require_role(admin, reviewer)`)
- `GET /workspaces/{id}/submissions` → list `portal_submissions`.
- `POST /workspaces/{id}/submissions/{sid}/review` `{status, note?}` → mark `reviewed`/`dismissed`
  (audited). A staff downloads an attached PDF via a signed URL and turns a verified doc into the
  real rights/consent record by hand (existing records flow) — the human-in-the-loop stays.

## Data model

### Tenant schema (migration `0020_tenant`; isolation test for the new table)
- **`portal_submissions`**: `id`, `kind` (`url_tip` | `needs_response`), `subject_id` (nullable
  int), `need_type` (nullable str), `body` (nullable text), `url` (nullable text),
  `file_key`/`file_name` (nullable), `status` (`new` | `reviewed` | `dismissed`),
  `submitted_by_staff_id` (int), `created_at`, `reviewed_by_staff_id` (nullable),
  `reviewed_at` (nullable).
- Add `CsamSource.portal_upload` (enum value only; no DDL — stored as `String(20)`).

## Services
- `services/portal.py` — the portal read serializers (minimization lives here, one place),
  submission create/list/review, the daily-cap check, and the PDF embedded-image scan
  (`_scan_pdf_images`, fail-closed). No counting of its own — reuses `metrics._needs_from_you`,
  `reports.read_artifact`/`list_reports`, `discovery.intake_urls`, `documents.store_document`,
  `csam.scan_image` + `csam_incidents.record_incident`.

## API summary
`/portal/*` (agency, `get_agency_session`); agency-user admin + `/workspaces/{id}/submissions*`
(staff). Errors: unknown subject → 404; missing text+file on a needs answer → 422; PDF that fails
type/CSAM → 422; over daily tip cap → 429.

## Frontend (`web/`, role-routed)
`App.tsx` renders `<AgencyPortal/>` when `me.role === "agency"`, else the staff `<Console/>`; staff
components are never imported into the portal tree. New `web/src/components/portal/*` reuse
`useToken` + the `request()` client + Tailwind conventions.

## Tests
- **default-deny** route walk (`test_portal_default_deny.py`).
- **minimization**, one per rule (`test_portal_minimization.py`): sensitive & ncii → domain-only
  `display_url`, never an image; timeline has no actor/note/reason; no offender/assignee/internal
  timestamps; no dismissed candidates; no provider-cost/metrics field; reports omit
  `generated_by_staff_id`.
- **IDOR / authz / revocation / MFA** (`test_portal_isolation.py`): agency A can't see B's data;
  revoked grant → 403 next request; agency can't be assigned/approver.
- **new-table isolation** (`test_portal_submissions_isolation.py`).
- **outsider PDF** (`test_portal_pdf_csam.py`): PDF with an embedded image + fake scanner `match`
  → 422, incident row, nothing stored.
- **daily tip cap**: over the cap → 429.
- Frontend vitest: agency role renders portal, not the staff console.

## Out of scope (Phase 2+)
Agency self-signup/billing; agency-initiated confirm/dismiss/file/approve/withdraw; inbox access;
multi-workspace agency users; email notifications to agencies; white-label.
