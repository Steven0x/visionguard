# ADR 0013: Reports & metrics (Slice 10)

Status: accepted (2026-09-28)

## Context

Slice 10 closes Phase 1. Staff need to hand paying agencies a report (agencies get reports, not
logins) and need an internal dashboard that proves the enforcement machine is working. Both must
be trustworthy: the customer report has to be reproducible and tamper-evident, and every number
across both surfaces has to be consistent.

## Decisions

### 1. One source of counting: `services/metrics.py`

Every number on the agency PDF and the internal page comes from `services/metrics.py`
(`report_metrics`, `metrics_summary`, plus the existing `removal_metrics`). The report renderer
and the API layer format; they never count. This is enforced by a test asserting the report's
JSON-snapshot totals equal the metrics-service output on the same fixture. Rationale: two counting
paths drift; a customer-facing number that disagrees with the internal number is a credibility
loss.

### 2. Metrics are per filing, snapshots are as-of

The funnel (found/filed/removed/pending) counts **filings** in the period, reusing Slice 9's
per-filing rule (a reopened, twice-filed case contributes two filings; `withdrawn` is excluded
from the removal denominator). "Open cases by status" and "still pending" are **as-of** snapshots
computed against a captured `as_of` timestamp, not the period — they answer "where do things stand
now", which is what an agency reads them as. `found` counts `Case`s created in the period (a case
is created at `confirmed`); a reopen reuses the case id, so reappearances show up in **re-upload
rate**, not as new "found".

### 3. Reports are append-only rows + write-once sealed artifacts

`reports` is append-only (trigger + REVOKE, like `notice_outcomes`). The PDF and a JSON snapshot
of its inputs are sealed **write-once** in the object-locked evidence bucket (reusing the Slice-7
`seal_object` machinery), and their SHA-256s are stored on the row. Rationale: a report handed to
a customer (and potentially cited in an enforcement dispute) must be regenerable and checkable
later — `verify_report` re-hashes the sealed bytes. We reuse the evidence bucket rather than the
assets bucket precisely because it is immutable and retained. We do **not** RFC 3161 timestamp
reports (that is for capture chain-of-custody); the append-only row + content hash is the
integrity anchor.

### 4. Data minimization is a render-layer concern, gated by a `sensitive` flag not the claim type

Cases are **counted** like any other claim (the agency needs to know the volume), but imagery is
**default-deny**: a thumbnail renders only when the case is `sensitive == FALSE` **and** the
per-report toggle is on. We deliberately do **not** gate on claim type, because leaked paid/intimate
content is usually filed as `copyright` — keying redaction on `claim_type == "ncii"` would leak the
exact imagery we must protect. Instead every case carries `cases.sensitive` (NOT NULL DEFAULT TRUE;
always TRUE and uncleanable for ncii; cleared only by an explicit, audited reviewer action).
Existing cases backfill as sensitive. ncii additionally renders domain-only URLs. Redaction lives in
the report service's rendering, keeping the counting layer claim-agnostic. A per-subject report
passes `subject_id` into every query and the renderer asserts a single subject — defense in depth
for tenant/subject isolation (#5).

### 5. `shown_at` added now for review-minutes

"Review minutes per case" needs the moment a candidate was shown to a reviewer, which we never
captured. We add `discovery_candidates.shown_at`, stamped once when `review.list_inbox` first
returns a candidate (never overwritten). Alternatives (deriving from audit rows, or the
`discovered_at`/`matched_at` pair) don't represent "shown" and would misstate the metric.

### 6. Internal page is per-workspace

The internal metrics endpoints are per-workspace (`GET /workspaces/{id}/metrics/...`), mirroring
Slice 9. A cross-workspace roll-up would require looping tenant schemas in application code (no
cross-tenant SQL join is allowed, #5); it is deferred to Phase 2. "Provider cost per workspace" is
therefore the current workspace's provider cost, shown per the workspace the staffer selects.

## Consequences

- Nothing is sent automatically (no scheduler, no email) — staff generate/review/download, all
  audited (#3).
- Adding a metric means adding it to `services/metrics.py` and surfacing it; the report and page
  pick it up without a second counting path.
