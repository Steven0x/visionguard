# ADR 0015: Agency portal (Slice 12)

Status: accepted (2026-09-29)

## Context

Phase 1 gave agencies reports, not logins. Slice 12 opens a narrow, invite-only portal so an agency
can self-serve a read-only view of its enforcement and take two tightly-scoped write actions. The
overriding risk is authorization: agency users must never reach the staff enforcement machine, must
only ever see their own workspace, and every portal response must be minimized. See
`docs/specs/portal.md`.

## Decisions

### 1. Agency users reuse the `Staff` table with a new `agency` role
An agency user is a `Staff` row with `role=agency`, `all_workspaces=False`, and exactly one
`StaffWorkspaceAccess` grant. Rationale: `get_current_staff` and `/me` already key on
`clerk_user_id` in `staff`; a separate `AgencyUser` table would fork the core auth lookup for no
real isolation gain (tenant isolation is enforced by the schema, not the identity table). The cost —
agency rows appearing in staff queries — is contained by excluding `role=agency` from every
staff-facing list (assignee/approver pickers, staff listings, counts) and by a test that an agency
user can never be assigned or recorded as an approver.

### 2. Workspace comes from membership, never the URL
Portal routes carry no `workspace_id`. `get_agency_context` resolves the single access grant from
`public_session` on every request, so cross-tenant IDOR is structurally impossible and **revocation
takes effect on the next request** (delete the grant → 403), not at token expiry.

### 3. Default-deny is enforced by a route-walk test, not vigilance
Role-gated staff routes already reject agency. To keep it that way as routes are added, a test walks
every registered route with an agency token and asserts 403 (allowlisting `/portal/*`, `GET /me`,
health). A new staff route that forgets its gate fails CI.

### 4. Agency writes create staff work; they never auto-confirm
A URL tip reuses `discovery.intake_urls` → a `pending` candidate in the staff review inbox. A "Needs
from you" answer is **persisted for staff review** in a new `portal_submissions` table — it is not
auto-turned into a rights/consent record (that would flow outsider input straight into legal-basis
records and bypass staff-authored validation). Staff verify and create the real record by hand.

### 5. Outsider-uploaded PDFs are CSAM-scanned (embedded images) and quarantined
The needs-answer PDF is the first outsider-uploaded file. We extract the embedded images `pypdf`
can enumerate (new pure-Python dependency — no system libs) and run each through the existing
`CsamScanner`, failing closed: a `match` records a `CsamIncident` (`CsamSource.portal_upload`) and a
scan `error`/unparseable PDF also rejects — both store no bytes and 422. Accepted files live under a
`quarantine/` key prefix that nothing renders inline; staff download them only as attachments, so an
image an extractor misses still can't auto-render to anyone. Rationale: CLAUDE.md #7 requires scanning
imagery at every storage choke point, and a PDF can smuggle images past a naive "it's a PDF" check.

### 6. The portal serves the sealed report PDF only
The report PDF is already minimized at generation (no thumbnails for sensitive/ncii; domain-only
ncii URLs) and sealed. The JSON input snapshot is an internal reproducibility artifact (raw numbers,
subject-id inputs) and stays staff-only.

### 7. Minimization lives in one place
`services/portal.py` holds the portal serializers. `display_url` is domain-only for `ncii` or
`sensitive` cases (full URL otherwise) and no image is ever returned; timelines expose transitions
only (no actor, reason, or note); reports/subjects/cases drop internal fields. Each rule has a test.

## Alternatives considered
- **Separate `AgencyUser` table** — rejected (§1): more code, forks auth, no isolation gain.
- **Auto-create draft rights/consent from a needs-answer** — rejected (§4): bypasses staff
  validation on legal-basis records.
- **Adding `agency` to `require_role(admin, reviewer)` on existing read routes** — rejected: those
  responses carry internal fields; a dedicated `/portal` surface with its own minimized models is
  safer than trying to redact the staff responses.
- **A poppler/pdfimages or pikepdf extractor** — rejected in favour of `pypdf` (pure-Python, no
  system dependency) for the embedded-image scan.

## Consequences
- A new dependency (`pypdf`) is added for outsider-PDF image extraction.
- Agency rows in `staff` must be filtered from staff-facing lists forever; the assign guard + test
  encode that.
- `portal_submissions` is a new tenant table (migration `0020_tenant`) with an isolation test.
