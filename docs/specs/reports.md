# Spec: Reports & metrics (Slice 10)

Status: draft. This is the last Phase-1 slice. It ships two things on top of the enforcement
loop built in Slices 1–9:

1. **Agency report (PDF)** — a per-workspace / per-subject, date-ranged report VisionGuard staff
   generate, review and hand to a paying agency (agencies get reports, not logins in Phase 1).
2. **Internal metrics page (staff only)** — the per-workspace operational dashboard.

**The counting lives in exactly one place.** `services/metrics.py` is the single source of every
number. The report layer and the metrics API do no counting of their own — they call the metrics
service and format. Test: report totals `==` metrics-service totals on the same fixture.

Non-negotiables in play:
- **#3 human in the loop.** Nothing is sent automatically. Staff generate, review and download;
  generation and download are audited. There is no scheduler and no email path here.
- **#5 tenant isolation.** `reports` is a tenant table with an isolation test. Every report query
  is workspace-scoped (tenant session); a **per-subject** report passes `subject_id` into every
  query and the renderer asserts no other subject's row reaches the page.
- **#6 evidence immutable / append-only.** `reports` is append-only (trigger + REVOKE, like
  `notice_outcomes`). The generated PDF + a JSON snapshot of its inputs are sealed **write-once**
  in the object-locked evidence bucket; the row stores each artifact's SHA-256 so a report can be
  regenerated and checked later.
- **#7 minimize sensitive data.** A report renders a case's thumbnail **only when the case is not
  sensitive AND the per-report toggle is on** — default-deny everywhere else. Leaked paid/intimate
  content is usually filed as **copyright**, so the claim type alone can't gate imagery; every case
  carries a `sensitive` flag (below). ncii cases additionally show **domain-only** URLs (never a
  full path).

See ADR `docs/adr/0013-reports-metrics.md`.

## Reproducibility

A report is computed **as of** a captured `as_of` timestamp. `generate_report`:
1. captures `as_of = now`, calls `report_metrics(...)`,
2. builds a deterministic **JSON input-snapshot** (`json.dumps(..., sort_keys=True)`) of the
   parameters + every number,
3. renders the **PDF** (reportlab), applying the redaction rules,
4. SHA-256s each artifact and **seals both write-once** under
   `{schema}/reports/{report_id}/report.pdf` and `.../inputs.json`,
5. stores the keys + hashes on the append-only `reports` row and audits `report.generated`.

`verify_report` re-fetches the sealed bytes, re-hashes, and compares to the stored SHA-256 (the
"checked later" path). Regenerating from the same inputs + `as_of` yields an identical JSON
snapshot.

## Agency report contents

Scope = whole workspace **or** a single subject; plus a date range `[start, end]` and a
thumbnails toggle. The PDF contains:

- **Funnel** — **Found**, **Filed**, **Removed** (split **verified** vs **staff-only**), median
  time to removal, **still pending**.
- **Open cases by status** — a snapshot as of `as_of` of non-terminal cases grouped by status.
- **Highlights** (2–3) — derived purely from the numbers above (e.g. total removed this period,
  fastest verified removal, most-hit platform). No extra queries.
- **Needs from you** — missing authorizations, photographer/ownership contacts, licensed-use
  confirmations, derived from blocked/unsupported claims (`claim_support().missing`) and
  dismissed-as-licensed review decisions.

## Metric definitions (with formulas)

All functions take a tenant `Session`. `report_metrics(session, *, subject_id=None, start, end,
as_of)` returns one dataclass with every agency-report number. Period bounds are inclusive dates.

**Funnel (period-bounded by the filing/case timestamp named):**
- **found** = count of `Case` rows with `created_at.date() ∈ [start, end]` (a case is created at
  status `confirmed`, i.e. a reviewer confirmed the match). Optionally filtered by `subject_id`.
  A reopen reuses the existing case id, so a reappearance is **not** re-counted as found (it is
  captured by re-upload rate instead).
- Iterate notices with `sent_at.date() ∈ [start, end]`, status ∈ `{sent, delivery_failed,
  withdrawn}` (a notice that left `draft` is a filing). For `subject_id`, join
  `Notice.case_id → Case.subject_id`. For each:
  - **filed** += 1.
  - `withdrawn` → **withdrawn** += 1 (excluded from the removal denominator).
  - else take the notice's effective outcome (latest non-superseded `notice_outcome`):
    - `removed` → **removed** += 1, and **removed_verified** if the case ever had a `gone`
      recheck else **removed_staff_only**; append `max(0, effective_at − sent_at.date())` days.
    - `countered` → **countered** += 1.
    - `None` / `rejected` / `no_response` → **still_pending** += 1.
  - So `filed = removed + countered + still_pending + withdrawn`.
- **median_days_to_removal** = median of the appended day counts (clamped ≥0), else `None`.

**Snapshot (as of `as_of`, not period-bounded):**
- **open_cases_by_status** = count of `Case` rows whose status ∉ `TERMINAL_STATES`
  (`dismissed, withdrawn, recovered, closed`), grouped by status; `subject_id` filter applies.

**Needs from you** (derived; no new counting primitive):
- The in-scope subjects are the given `subject_id`, or every subject that currently has a
  non-terminal case or a pending discovery candidate. For each, `claim_support(...)` yields
  `missing` reasons, aggregated into buckets:
  - **missing_authorization** ← `"active agent authorization"`.
  - **ownership_rights** ← the copyright ownership-record reason (photographer license / copyright
    registration / self-owned declaration) — "get a photographer contact / ownership proof".
  - **enforcement_consent** ← `"active enforcement consent"` (likeness/ncii/impersonation).
- **licensed_use_confirmations** = count of `ReviewDecision` rows with `reason == licensed` in the
  period for the in-scope subjects (the agency should confirm those uses are actually licensed).

**Highlights** = up to three non-empty of: `"{removed} removed this period"`, `"fastest verified
removal in {min_verified_days}d"`, `"most-hit platform: {platform} ({n} filings)"`.

### Internal metrics (per workspace) — `metrics_summary(session)`

- **removal_rate** = `removed / (filed − withdrawn)` per `(platform, claim_type)`. *(existing
  `removal_metrics`)*.
- **median_time_to_removal** = median(`effective_at − sent_at`) per `(platform, claim_type)`.
  *(existing)*.
- **review_precision** = `(filed − withdrawn) / filed` over all filings — of filings that reached
  a platform, the fraction not later retracted. `None` when `filed == 0`.
- **wrong_filing_rate** = `withdrawn / filed` — `Withdrawn` is always a wrong-claim retraction
  (cases spec). Complement of precision; both reported per the "done when". `None` when `filed==0`.
- **re_upload_rate** = `reopened / removed`, where **reopened** = `CaseEvent` rows with
  `kind=transition, to_status=discovered, reason=reappearance` (the reopen path) and **removed** =
  real `filed→removed` transitions (`CaseEvent kind=transition, to_status=removed`). Both from the
  timeline, never a bare status snapshot. `None` when `removed == 0`.
- **review_minutes_per_case** = median over decided candidates (a `ReviewDecision` whose candidate
  has a non-null `shown_at`) of `(decided_at − shown_at)` in minutes. `None` when none.
- **provider_cost** = `sum(DiscoveryRun.estimated_cost_cents)` grouped by `provider` (the
  per-workspace cost — the session is tenant-scoped), plus a total.

The `test` anchor is one fixture workspace with a **reopened (twice-filed)** case and a
**withdrawn** case, hand-computed for every metric.

## `shown_at` was not previously captured — added in this slice

Review-minutes needs the moment a candidate was **shown** to a reviewer. Before Slice 10 we only
captured `discovered_at` (created), `matched_at` (set on confirm) and `ReviewDecision.decided_at`
— not "shown". This slice adds `discovery_candidates.shown_at` (nullable timestamptz), **stamped
once** the first time `review.list_inbox` returns a candidate whose `shown_at` is null (never
overwritten). Review-minutes = `decided_at − shown_at`.

## The `sensitive` case flag (default-deny for report imagery)

Claim type can't gate imagery on its own — leaked paid/intimate content is routinely filed as
`copyright`. So every case carries `cases.sensitive` (boolean, **NOT NULL DEFAULT TRUE**):

- **TRUE at confirm** (set when the case is opened) and **TRUE for every pre-existing case**
  (backfilled by the migration).
- **Always TRUE and uncleanable for `ncii`** — `clear_sensitive` refuses an ncii case (422).
- A reviewer clears it (sets FALSE) only via an **explicit, audited action**
  (`POST /cases/{id}/clear-sensitive`, audit `case.sensitive_cleared`).
- **Report thumbnails render only when `sensitive == FALSE` AND `include_thumbnails == TRUE`.**
  Every other combination renders no image.

## Data model

### Tenant schema (migration `0019_tenant`; isolation test for the new table)
- **`cases` + `sensitive`** (boolean, NOT NULL DEFAULT TRUE — backfills existing cases as sensitive).
- **`discovery_candidates` + `shown_at`** (nullable timestamptz).
- **`reports`** (append-only; trigger + REVOKE like `notice_outcomes`): `id`, `subject_id`
  (nullable int, null = whole workspace; no cross-schema FK, like other tenant tables),
  `period_start` (date), `period_end` (date), `as_of` (timestamptz), `include_thumbnails` (bool),
  `pdf_key` (text), `pdf_sha256` (text), `json_key` (text), `json_sha256` (text),
  `generated_by_staff_id` (int), `created_at`.

## Services

### `services/metrics.py`
- keeps `removal_metrics`; adds `report_metrics(...)` and `metrics_summary(...)` (all pure reads),
  reusing `_FILED_STATUSES`, `effective_outcome`, and the `gone`-recheck verification set.

### `services/reports.py` (the only writer of `reports`)
- `generate_report(session, *, workspace, subject_id, start, end, actor_staff_id,
  include_thumbnails) -> Report` — the flow under **Reproducibility**.
- `list_reports(session, subject_id?)`, `get_report(session, report_id)`,
  `verify_report(session, report) -> bool`.
- **Redaction** (applied at render, not in counting): ncii → no image + domain-only URL;
  non-ncii → thumbnails only when `include_thumbnails`; per-subject → assert single subject.

## API (`/workspaces/{id}`, admin+reviewer; mirrors `routers/outcomes.py`)
- `POST /reports` — `{subject_id?, start, end, include_thumbnails?}` → generate; returns metadata
  (id, hashes, period, as_of). Audited (`report.generated`).
- `GET  /reports` — list (optional `subject_id`).
- `GET  /reports/{rid}.pdf` — stream the sealed PDF (`application/pdf`, attachment). Audited
  (`report.downloaded`).
- `GET  /reports/{rid}/inputs.json` — the sealed JSON snapshot. Audited.
- `GET  /metrics/summary` — the internal-page payload. `GET /metrics/removals` stays.

Errors: `start > end` → 422; report referencing an unknown subject → 404.

## Out of scope (Phase 2+)
Automated sending/scheduling of reports; a customer portal; cross-workspace roll-ups; demand
letters / recovery; deepfake/likeness identity gates.
