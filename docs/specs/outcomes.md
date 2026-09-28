# Spec: Outcomes & re-upload watch (Slice 9)

Status: draft. This slice closes the enforcement loop after a notice is **filed** (Slice 8): it
records what the platform actually did, chases overdue filings on each platform's own response
window, **watches the URL** to propose (never assert) a removal, moves removed cases through a
**Monitoring** window to `Closed`, and **reopens** a monitored case when the same infringement
reappears — all onto the **existing** case state machine, with no new states. It also computes
the removal-rate and time-to-removal metrics the slice is judged on.

Non-negotiables in play:
- **#3 a human approves every filing / decides every transition.** The URL re-check only
  *proposes* an outcome; a human confirms it. Nothing outbound is added. A **reopened** case
  never reuses the prior notice's approval — it needs a fresh draft and a fresh human approval.
- **#5 tenant isolation.** `notice_outcomes` and `url_rechecks` are tenant tables with isolation
  tests. `channels.response_window_days` is added to the existing global (public) reference row.
- **#6 evidence is immutable.** A confirmed removal seals a fresh `proof_of_removal` capture via
  the Slice-7 machinery (the 404/take-down page). Outcomes are **append-only**: a mistake is
  corrected by appending a **superseding** row, never by editing.
- **#8 allowlist first / consent before action.** Reopening a monitored case re-runs the confirm
  guards — active authorization (consent), claim support, and the allowlist — before the case can
  move again. A source allowlisted since the case last closed blocks the reopen.
- **Audit** on every outcome, proposal, reopen, and lifecycle transition.

See ADR `docs/adr/0012-outcomes-recheck.md`.

## Outcomes map onto the existing state machine (no new states)

An **outcome** is a recorded platform response on a **filed** notice. Only two outcomes move the
case; the other two are recorded without a transition and keep the case on the follow-up list.

| Outcome        | Case effect (via `cases.transition`)                    |
| -------------- | ------------------------------------------------------- |
| `removed`      | `filed → removed` (triggers the `proof_of_removal` seal) |
| `countered`    | `filed → countered`                                     |
| `rejected`     | **no transition** — stays `Filed`; staff then **escalate** (`filed → escalated`) or **withdraw** (`filed → withdrawn`) |
| `no_response`  | **no transition** — stays `Filed`; resets the follow-up timer for the next nudge |

`rejected` and `no_response` are pure records: the case stays `Filed` and the existing
`filed → escalated` / `filed → withdrawn` endpoints handle the staff's next move (re-file =
escalate; wrong-claim = withdraw + `cases.refile`). Recording either resets `due_at` so the case
resurfaces on the follow-up list after the platform's window.

## Metrics are per filing, not per case

A case can be filed more than once (reopen → re-file), so **metrics count filings (notices), not
cases**. A reopened-and-refiled case contributes **two** filings.

- **Removal rate** per `(platform, claim_type)` = `removed / (filed − withdrawn)`. `withdrawn`
  filings are excluded from the denominator and reported separately (CLAUDE.md / cases spec). The
  **count still pending** (filed, no terminal outcome yet) is reported alongside so young filings
  are visible and don't silently depress the rate.
- **Median time to removal** = `effective_at − filed_at`, where `filed_at` is the notice's
  `sent_at` and `effective_at` is the removal's **effective date** (below) — *not* the event
  timestamp, which is just when a human got around to confirming.
- Computation lives in `services/metrics.py`; `GET /workspaces/{id}/metrics/removals` exposes it.
  The polished internal metrics page is still Slice 10 — this ships the numbers + a minimal
  readout, which is what Slice 9's "done when" requires.
- **Verified vs staff-only removals.** `removed` is split into `removed_verified` (the case has a
  `gone` recheck) and `removed_staff_only` (recorded by staff, never recheck-verified). A soft-404
  platform (which never returns `gone`) thus reports honest numbers instead of implying
  recheck-proven take-downs. (Verification is per **case**, so a reopened, twice-filed case with a
  single `gone` counts both filings as verified — acceptable at Phase-1 volumes.)

### `effective_at` (the date the platform acted)
`notice_outcomes.effective_at` is a staff-entered date for when the content actually went down.
It **defaults** to the earliest `gone` recheck in the consistent run that triggered the proposal,
and to `now` if there is none. Time-to-removal uses it so an operator confirming a week late
doesn't inflate the metric.

## Follow-up reminders run on each platform's window

`channels.response_window_days` (nullable int, global reference data) records how long a platform
usually takes. On **filing** (`send` / `record_hand_submission`), the notices service sets the
case `due_at = now + response_window_days` (falling back to `case_due_days_map["filed"]` when the
channel has none). **Overdue follow-ups** are open `filed` cases past `due_at` with no terminal
outcome — surfaced at `GET /workspaces/{id}/follow-ups` (reusing the case list's `overdue`
filter, scoped to `filed`).

## Automated URL re-check (SafeFetcher, scheduled)

A daily beat task **probes** the URL of every open `filed` and `monitoring` case through the
existing SSRF-safe fetcher and appends a `url_rechecks` row. The probe **must not download the
body** — it reads the HTTP status and closes the stream (see `SafeFetcher.probe`).

**Which URL:** probe `page_url` (the hosting page) as the primary signal, falling back to
`source_url` only when `page_url` is null; the probed URL is recorded on the row. Image
`source_url`s are usually CDN links and are unreliable — signed CDN URLs expire (false `gone`)
and CDNs keep serving bytes after a page is removed (false `live`).

**Classification** (`services/recheck.classify`):
- `gone` — `404`, `410`, `451`, or a connection refused/failure.
- `live` — a `2xx` response.
- `error` — anything else (`401`/`403` = login wall, `429` = rate limit, `5xx`, timeouts). These
  are **inconclusive**, never `gone`.

**Soft-404s.** Many platforms return `200` for removed content, so **`live` is not proof of
anything** and **nothing ever auto-transitions on `live`**. The signal is only ever used to:

- **Filed case → propose `removed`.** Only when the **two most-recent** rechecks are both `gone`
  and at least **24h apart** (a single `gone` can be a geo-block / login wall / rate limit). Sets
  `cases.removal_proposed_at`. A human confirms via `record_outcome(removed)` (which seals the
  proof) or dismisses the proposal (clears the flag; case stays `Filed`).
- **Monitoring case → propose reappearance.** Only on a **`gone → live` transition** in
  `url_rechecks` (the previously-down URL is serving a page again), never on a plain standing
  `live`. Sets `cases.reappearance_proposed_at`. A human confirms → `cases.reopen_case` (reusing
  the case's existing candidate for a same-URL reappearance).

The task never raises (eager-safe, per-workspace), like the other beat tasks.

## Monitoring lifecycle (auto)

A daily beat task `run_monitoring_lifecycle` runs the tail of the machine as system housekeeping
(actor `None`, audited — no outbound action, so #3 is not implicated):
1. **`removed → monitoring`** once the case's `proof_of_removal` capture has sealed, setting
   `due_at = now + case_due_days_map["monitoring"]` (the watch window).
2. **`monitoring → closed`** once that window has elapsed with no reappearance proposal pending —
   **unless the removal was never recheck-verified** (below).

### Unverified removals never auto-close
A mistaken `removed` (e.g. staff auto-confirmed a soft-404) would otherwise silently auto-close
while the content is still up. Only a **`gone`** observation verifies a take-down, so before
`monitoring → closed`: if the case was probed since the removal was recorded but **no `gone` was
ever observed** — the URL kept serving a page (soft-404) or was only ever unreachable/blocked
(login wall, rate limit) — the case is **not** closed. Instead `cases.removal_unverified_at` is
set (audited) and the case is surfaced on the case view **and the follow-ups list** for a human to
**confirm-close** (`monitoring → closed`) or **reopen** (`cases.reopen_case`, same
consent/allowlist/claim re-checks and fresh-approval requirement). A later `gone` recheck clears
the flag (audited) and lets the normal auto-close proceed; no rechecks at all since the removal
does not flag it (nothing contradicts the staff-recorded removal).

## Reopen on reappearance (no duplicate cases)

When new discovery finds the same infringement while a case is in `monitoring`, we **reopen that
case with its history attached** instead of opening a duplicate.

### Matcher (`cases.find_monitoring_case`)
Given a candidate for a subject, find a `monitoring` case for the **same subject** matching by:
1. **same URL** — equal `source_key`; or
2. **same platform account** — equal `offender_key` when it is account-scoped (a platform or
   marketplace key, i.e. not a bare `domain:` key); or
3. **same host + same matched asset** — equal host **and** equal non-null `matched_asset_id`,
   **only when the host is not a platform** (`offender_key` is a `domain:` key).

Platform detection is `offender_key`'s existing knowledge (`services/offender.py`, which encodes
the same platform set as the channel registry): a `domain:` prefix means a non-platform host.
**Domain-alone never merges on a platform host** — two different posts on `instagram.com` /
`x.com` / `reddit.com` for the same subject are distinct offences and must **not** merge
(tested). Only an exact account or exact URL merges on a platform.

### `cases.reopen_case(case, candidate, actor)`
- Precondition: `case.status == monitoring`.
- **Re-check the confirm guards** (bypass = bug): active authorization / consent
  (`subject_enforcement`), claim still supported, and the allowlist (`is_allowlisted`). Failure
  raises exactly as confirm does — a since-allowlisted or now-unauthorized source cannot reopen.
- `monitoring → discovered` (reason `reappearance`) then `discovered → confirmed`, both audited
  with `case_event`s; the case keeps its id and full prior timeline.
- Point the case at the reappearance: update `candidate_id` / `source_url` / `source_key` /
  `page_url` / `offender_key` to the new candidate (a same-URL reappearance reuses the existing
  candidate), write a `link` event, clear `reappearance_proposed_at`, and trigger a fresh
  `auto` evidence capture (like a first confirm).
- Audit `case.reopened`.
- **A reopened case starts a new filing cycle.** The prior notice is `sent`/`withdrawn` and does
  **not** carry its approval forward: `create_draft` only refuses when an **active**
  (`draft`/`delivery_failed`) notice already exists, so a reopened `confirmed` case drafts a new
  notice and requires a new human approval before it can be filed again (tested).

`review.confirm_candidate` calls the matcher first: a monitoring match routes to `reopen_case`
(re-checking the same guards it already runs), otherwise it opens a new case as before.

## Data model

### Public schema (migration `0017_public`)
- **`channels`** + `response_window_days` (nullable int). Seed values backfilled per platform.

### Tenant schema (migration `0018_tenant`; isolation tests for both new tables)
- **`cases`** + `removal_proposed_at` (nullable, Filed proposal) + `reappearance_proposed_at`
  (nullable, Monitoring proposal) + `removal_dismissed_at` (nullable, suppresses re-proposal).
- **`notice_outcomes`** (append-only; trigger + REVOKE like `notice_versions`): `id`,
  `case_id` (FK), `notice_id` (FK), `outcome` (`removed|rejected|countered|no_response`),
  `source` (`manual|auto_confirmed`), `effective_at` (date), `note`, `supersedes_id`
  (nullable FK to a prior outcome it corrects), `recorded_by_staff_id`, `created_at`. The
  **latest non-superseded** row per notice is the effective outcome.
- **`url_rechecks`** (append-only): `id`, `case_id` (FK), `probed_url`, `http_status`
  (nullable), `result` (`live|gone|error`), `detail`, `created_at`.

Public Staff ids are plain ints (no cross-schema FK), like `cases` / `notices`.

## Services

### `services/outcomes.py` (the only mutator of `notice_outcomes`)
- `record_outcome(case, notice, outcome, *, effective_at?, note?, source=manual, actor)`:
  case must be `filed`; append a `notice_outcomes` row (defaulting `effective_at` per above);
  `removed`→`transition(filed→removed)`, `countered`→`transition(filed→countered)`,
  `rejected`/`no_response`→ reset `due_at`; clear `removal_proposed_at`; audit
  `case.outcome_recorded`.
- **Correcting a mistake** (append-only): `record_outcome(..., supersedes_id=<prior>)` appends a
  correcting row linked to the one it replaces — never an edit; the latest row wins. Corrections
  are allowed **while the case is still Filed** (e.g. `no_response` → `rejected`, or fixing an
  `effective_at`). A wrongly-recorded **`removed`** has already transitioned the case (the machine
  has no false-removal reverse — CLAUDE.md); if the content is in fact still up, that is handled by
  the monitoring re-check / **reopen** path, not by a supersede.
- `dismiss_removal_proposal(case, actor, note)`: clears `removal_proposed_at` and records
  `removal_dismissed_at`; audits. The dismissal suppresses re-proposal until a **fresh** two-check
  `gone` streak accrues entirely after it (the immutable rechecks that triggered it can't re-raise
  it on the next beat).
- reads: `list_outcomes(case)`, `effective_outcome(notice)`.

### `services/recheck.py`
- `classify(http_status | None) -> RecheckResult`.
- `record_recheck(case, probed_url, status)`: append a `url_rechecks` row.
- `evaluate_filed(case)`: two-most-recent `gone` ≥24h apart → set `removal_proposed_at`.
- `evaluate_monitoring(case)`: newest row is `live` and the prior is `gone` → set
  `reappearance_proposed_at`.

### `services/metrics.py`
- `removal_metrics(session) -> list[PlatformClaimMetric]` (per `platform`×`claim_type`:
  `filed`, `withdrawn`, `removed`, `pending`, `removal_rate`, `median_days_to_removal`). Pure
  read over `filing_log` / `notices` + `notice_outcomes`; tested against a hand-computed fixture
  that **includes a reopened (twice-filed) case and a withdrawn one**.

### `SafeFetcher.probe(url) -> ProbeResult`
Reuses the pinned-IP, per-hop-revalidated redirect machinery, but issues a status-only request
that **does not read the response body**, enforcing the same timeout, redirect cap, and — since
no body is downloaded — no size read. `FakeFetcher.probe` returns a deterministic/injectable
status for tests.

## Workers (beat)
- `recheck_open_urls` (daily): probe filed + monitoring cases; append rechecks; run
  `evaluate_filed` / `evaluate_monitoring`. Eager-safe.
- `run_monitoring_lifecycle` (daily): `removed → monitoring` (proof sealed) then
  `monitoring → closed` (window elapsed). Eager-safe, system-actor, audited.

## API (`/workspaces/{id}`, admin+reviewer)
- `GET  /cases/{cid}/outcomes` — recorded outcomes + the effective one + proposal flags.
- `POST /cases/{cid}/outcomes` — record an outcome (`outcome`, `effective_at?`, `note?`).
- `POST /cases/{cid}/outcomes/dismiss-removal-proposal` — note required.
- `POST /cases/{cid}/reopen` — confirm a reappearance proposal (same-URL reopen).
- `GET  /follow-ups` — open filed cases overdue on their platform window.
- `GET  /metrics/removals` — per-platform × claim removal metrics.
- `GET  /cases/{cid}/rechecks` — the recheck history (for the case view).

Errors: outcome on a non-`filed` case → 409/422; reopen guard failure (allowlist / no auth /
unsupported claim) → 422; illegal transition → 422.

## Out of scope (later)
The polished internal metrics page + monthly customer reports (Slice 10 — **now delivered**, see
`docs/specs/reports.md`); automated re-filing; demand letters / recovery; deepfake/likeness
identity gates (Phase 2).
</content>
</invoke>
