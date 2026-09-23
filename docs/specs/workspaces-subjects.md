# Spec: Workspaces & Subjects (Slice 1)

Status: implemented in Slice 1. Source of truth for the workspace + subject data model,
endpoints, and validation. Changes to behaviour must update this file in the same PR.

## Goal

VisionGuard staff can set up an agency workspace and load its roster of protected people.
No customer logins (staff only). Vertical slice: UI → API → DB.

## Roles

- **admin** — create/edit workspaces; edit the allowlist; everything a reviewer can do.
- **reviewer** — view workspaces they have access to; full subject CRUD + CSV import.
- Every workspace-scoped route also requires an access grant (`StaffWorkspaceAccess`) unless
  the staff member is an admin with `all_workspaces`. Enforced by `require_workspace_access`
  (`api/app/auth/deps.py`) before any tenant session opens.

## Data model

### Public schema — `workspaces` (extended)

Existing: `id`, `name`, `slug` (unique, immutable), `plan`, `created_at`.
Added in Slice 1: `contact_name` (nullable), `contact_email` (nullable).

### Tenant schema (per workspace, `ws_<id>`)

**`subjects`**

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| legal_name | varchar(200) NOT NULL | |
| stage_names | text[] NOT NULL default `{}` | trimmed, de-duped, case preserved |
| handles | text[] NOT NULL default `{}` | normalized (see below) |
| residence_state | char(2) nullable | US state code or null |
| biometrics_blocked | bool NOT NULL default true | derived server-side (see below) |
| status | varchar(20) NOT NULL default `active` | `active` \| `archived` |
| notes | text nullable | |
| created_at / updated_at | timestamptz | `updated_at` on update |

**`allowlist_entries`**

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| kind | varchar(20) NOT NULL | `domain` \| `handle` \| `url` \| `account` |
| value | varchar(500) NOT NULL | |
| note | varchar(500) nullable | |
| created_at | timestamptz | |

Both are tenant tables → each has a tenant-isolation test (CLAUDE.md #5).
`stage_names`/`handles` are `text[]` for Slice 1; Slice 3 may normalize into a structured
identifiers table when discovery needs platform/handle rows.

## Rules

### Biometrics — fail closed (CLAUDE.md #9)

`compute_biometrics_blocked(residence_state)` = `residence_state not in
BIOMETRICS_ALLOWED_STATES`, where `BIOMETRICS_ALLOWED_STATES = US_STATES − {IL, WA}`.

- **Blocked is the default.** Cleared **only** when residence is a known US state outside
  IL/WA. `null`/blank/unknown residence and any non-US residence stay **blocked**.
- Derived server-side on every create/edit/import. A client-supplied `biometrics_blocked` is
  **ignored** — the UI shows it read-only and can never clear it.
- Slice 1 has no counsel-override to clear the block for other reasons (later slice).

### Handle normalization

`normalize_handles(list[str])`, applied on create, edit **and** import so discovery sees
consistent values: trim whitespace; strip a leading `@`; lowercase; preserve a `platform:`
prefix when present (`IG:@JaneDoe` → `ig:janedoe`); drop empties; dedupe (order-preserving).
`stage_names`: trim, drop empties, dedupe exact (case preserved).

## Endpoints

All under `/workspaces`. `401` unauth, `403` role/access failure, `404` missing.

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/workspaces` | admin | create; grants creator access; audit `workspace.created` |
| GET | `/workspaces` | admin/reviewer | workspaces the caller can access |
| GET | `/workspaces/{id}` | admin/reviewer + access | details incl. allowlist |
| PATCH | `/workspaces/{id}` | admin + access | edit name/contact/plan; audit `workspace.updated` |
| GET | `/workspaces/{id}/allowlist` | admin/reviewer + access | list |
| POST | `/workspaces/{id}/allowlist` | admin + access | add; audit `allowlist.entry_added` |
| DELETE | `/workspaces/{id}/allowlist/{entry_id}` | admin + access | remove; audit `allowlist.entry_removed` |
| GET | `/workspaces/{id}/subjects` | admin/reviewer + access | `?status=active\|archived\|all` (default active) |
| POST | `/workspaces/{id}/subjects` | admin/reviewer + access | audit `subject.created` |
| GET | `/workspaces/{id}/subjects/{sid}` | admin/reviewer + access | |
| PATCH | `/workspaces/{id}/subjects/{sid}` | admin/reviewer + access | audit `subject.updated` |
| POST | `/workspaces/{id}/subjects/{sid}/archive` | admin/reviewer + access | status→archived; audit `subject.archived` |
| POST | `/workspaces/{id}/subjects/import/preview` | admin/reviewer + access | multipart; validates only, no writes |
| POST | `/workspaces/{id}/subjects/import/commit` | admin/reviewer + access | multipart; all-or-nothing; audit `subjects.imported` |

Slug is auto-derived from the name (unique) when not supplied; it is immutable after create.

## CSV import

- **Format:** header row; columns `legal_name` (required), `stage_names`, `handles`,
  `residence_state`, `notes`. `stage_names`/`handles` are `;`-separated.
- **Encoding:** decoded as `utf-8-sig` (handles a UTF-8 BOM). A file that isn't valid UTF-8
  text/CSV (e.g. binary) is rejected `422`.
- **Limits:** rejected if larger than `SUBJECT_IMPORT_MAX_BYTES` (~1 MB) or more than
  `SUBJECT_IMPORT_MAX_ROWS` (~1000) rows.
- **Per-row validation:** legal_name non-empty & ≤200; residence_state (if given) a valid US
  state; handles normalized; length caps.
- **Duplicate detection (an error):** a row duplicates another when `legal_name` (trimmed,
  case-insensitive) matches **and** at least one normalized handle overlaps — checked against
  (a) other rows in the same file and (b) existing **active** subjects in the workspace.
  Name-only matches and matches against **archived** subjects are not duplicates.
- **Preview** returns every row with `{row_no, values, errors[]}` and writes nothing.
- **Commit** is **all-or-nothing**: if any row has an error → `422` with the per-row errors and
  nothing is inserted; otherwise all rows insert in one tenant transaction and one
  `subjects.imported` audit row is written with the count.

## Audit

Every mutation writes one `audit_log` row in the workspace's tenant schema via `record_audit`
(`api/app/audit/service.py`): `workspace.created`, `workspace.updated`,
`allowlist.entry_added`, `allowlist.entry_removed`, `subject.created`, `subject.updated`,
`subject.archived`, `subjects.imported` (meta: count).

## Isolation & tests

- Isolation test per new tenant table (`subjects`, `allowlist_entries`): workspace A cannot
  read B's rows.
- A reviewer without access to a workspace gets `403` listing its subjects and on both import
  endpoints.
- Biometrics fail-closed, handle normalization, CSV limits/BOM/non-text, duplicate detection,
  archive-no-hard-delete, and audit-written are all covered by tests.

## Notes / deferred (from Slice 1 review)

- **`biometrics_blocked` is a GEO block only**, not a consent signal. `biometrics_blocked ==
  false` means residence permits biometrics — it is necessary but **not sufficient** for face
  work, which still requires an active biometric `ConsentRecord` (CLAUDE.md #1, Slice 2). Do
  not treat this flag as "face matching allowed."
- **CSV formula injection:** imported text (legal_name, notes, etc.) is stored verbatim (no
  apostrophe-escaping) to avoid corrupting legal names. Neutralization is the **export**
  layer's responsibility — any CSV/XLSX export (Slice 10 reports) MUST neutralize cells
  beginning with `= + - @ \t \r`.
- **Allowlist authorization basis:** `kind` captures the locator type (domain/handle/url/
  account), not *why* an entry is trusted (own-account vs licensee vs reseller). Slice 5
  (allowlist enforcement in review) likely needs an explicit `authorization_basis` field so a
  suppressed match records the legal basis for not filing. `note` is a free-text stopgap.
- `updated_at` is maintained by the ORM (`onupdate`), not a DB trigger; all writes go through
  the ORM.
- Upload bodies are read in capped chunks (`SUBJECT_IMPORT_MAX_BYTES`) so an oversized file
  can't be buffered whole before the size check.
