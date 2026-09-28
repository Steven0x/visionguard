# Spec: Cases & the lifecycle (Slice 6)

Status: draft. A **case** is a confirmed match under enforcement. The **case service is the
only way to change a case's state** — routers and other services never write `status`
directly. Every transition is validated against the state machine, guarded against concurrent
double-writes, and recorded as a `case_event` (the timeline) plus an audit entry.

Non-negotiables in play: **every case has a claim** (CLAUDE.md #4 — `→ filed` re-checks a
supported claim), **a human approves every filing** (#3 — a human drives every transition),
**tenant isolation** (#5), **audit** every transition.

## State machine (enforced exactly; every other pair is rejected)

```
discovered → confirmed | dismissed
confirmed  → filed
filed      → removed | countered | escalated | withdrawn
countered  → escalated | closed
removed    → monitoring
monitoring → discovered | closed          # discovered = reappearance (Slice 9 auto-reopens)
escalated  → recovered | closed
withdrawn | dismissed | recovered | closed → (terminal)
```

`TERMINAL = {dismissed, withdrawn, recovered, closed}`; **open** = all others
(`discovered, confirmed, filed, removed, monitoring, escalated, countered`). A Slice-5 confirm
opens the case at `confirmed` (initial event `→ confirmed`); `discovered` is entered only via
`monitoring → discovered`.

- **`withdrawn`** (terminal): the filed notice is **retracted**. `filed → withdrawn` **requires
  a note** (e.g. "wrong claim type"). It is *not* a removal.
- **`countered`** is **not** terminal: after a counter-notice we may `escalate` or `close`.

### Changing the claim type
`claim_type` is editable only while `discovered`/`confirmed`, and is **locked once `filed`**.
To correct a wrong claim after filing: `filed → withdrawn` (with a note), then **open a new
case from the same candidate** under the correct claim via `refile`. The duplicate check
ignores terminal cases, so a withdrawn case never blocks the re-file. The two cases are
**linked in both timelines** (a `link` event each). We do **not** route claim changes through
`removed`/`monitoring` — that would write a false `removed` into history and corrupt
removal-rate metrics.

### Metrics note (Slice 10)
Removal-rate and time-to-removal count **only real `removed` transitions** (from `case_events`).
`withdrawn` cases are **excluded from the denominator** and reported separately.

## `→ filed` preconditions (re-checked at transition time, not trusting the inbox)
1. an **active agent authorization** for the subject;
2. the case's `claim_type` is **still supported** by the subject's records (claims matrix);
3. `requires_evidence_pack(case)` — a **placeholder returning `True`** in Phase 1 (filing is
   allowed now). Slice 7 replaces the body to require an immutable `EvidencePack`; this is the
   single choke point where that gate lands.

## Data model (migration `0011_tenant`; isolation tests for the new tables)

- **`cases`** (extended; `Case`/`CaseStatus` move to `models/cases.py`): + `source_url`,
  `source_key` (sha256 of the canonical URL), `offender_key`, `assigned_staff_id`, `due_at`.
  **Partial unique index** `(subject_id, source_key) WHERE status NOT IN (terminal)` → **no two
  open cases** for the same subject + canonical URL (the service also checks → friendly 409).
- **`case_events`** (timeline): `case_id`, `kind` (`created|transition|claim_change|assignment|
  link`), `from_status`, `to_status`, `related_case_id` (for `link`), `actor_staff_id`,
  `reason`, `note`, `created_at`.
- **`case_notes`** (append-only; no update/delete path): `case_id`, `author_staff_id`, `body`,
  `created_at`.

## Follow-up timers
`case_due_days` is **config** (per state, e.g. `confirmed:2,filed:3,removed:1,countered:5,
escalated:7,monitoring:14`). A transition sets `due_at = now + days[new_state]` (terminal
states clear it). **Overdue** = open ∧ `due_at < now`; surfaced in the list.

## Offender grouping
`offender_key(url)` (`services/offender.py`, documented heuristic): known platforms →
`platform:@handle` (instagram/x/tiktok/onlyfans/…); parseable marketplaces → `etsy:<shop>`,
`ebay:<seller>`; otherwise `domain:<host>`. Stored on the case at creation; the list is
groupable/filterable by it.

## Case service (`services/cases.py`) — the only mutator
- `open_case_from_candidate(...)` (used by `review.confirm_candidate`): dup-check, set
  source/offender/`due_at`, status `confirmed`, initial `created` event, audit `case.created`.
- `transition(case, to, actor, reason?, note?)`: validate table; **conditional
  `UPDATE ... WHERE status=<from>`** (loser → 409); `→ filed` runs the preconditions; `→
  withdrawn` requires a note; sets `due_at`; `case_event` + audit `case.transition`.
- `change_claim(case, new, note, actor)`: only in `discovered`/`confirmed` (else 422);
  re-checks support; `claim_change` event + audit.
- `refile(case, new_claim, note, actor)`: source must be `withdrawn`; re-check auth + support;
  open a new confirmed case from the same candidate; write reciprocal `link` events; audit
  `case.refiled`.
- `add_note` (append-only), `assign(staff_id)` (validates workspace access) — audited;
  assign emits an `assignment` event.
- reads: `list_cases(subject/status/claim_type/offender_key/assignee/overdue/min_age_days)`,
  `offender_summary()`, `get_case`, `timeline`, `allowed_transitions(case)`.

## API (`/workspaces/{id}`, admin+reviewer)
`GET /cases` (filters + `overdue`), `GET /cases/offenders`, `GET /cases/{id}` (case + timeline +
notes + `allowed_transitions` + candidate/asset refs), `POST /cases/{id}/transition`,
`POST /cases/{id}/claim`, `POST /cases/{id}/refile`, `POST /cases/{id}/notes`,
`POST /cases/{id}/assign`. Illegal transition → 422; race loser → 409; Filed precondition
fail → 422.

## Reopen & the monitoring tail (Slice 9)
`monitoring → discovered → confirmed` is now driven by `cases.reopen_case` when a reappearance is
confirmed (a candidate matching a monitoring case, or a same-URL re-check proposal). Reopen
re-runs the confirm guards (authorization/consent, claim support, allowlist), keeps the case id +
timeline, points the case at the new candidate, and triggers a fresh capture — a reopened case
starts a **new filing cycle** (the prior notice's approval is never reused). The
`removed → monitoring → closed` tail runs on a daily beat (system actor, audited): advance once
the `proof_of_removal` capture seals, close once the watch window (`case_due_days["monitoring"]`)
elapses with no reappearance pending. See `docs/specs/outcomes.md` and ADR 0012.

## Out of scope (later)
Evidence capture fills `requires_evidence_pack()` (Slice 7); notice/filing (Slice 8); the metrics
*reporting/UI* + monthly customer reports (Slice 10 — the removal-metrics **computation** landed
in Slice 9, `services/metrics.py`).

> **Note for Slice 8:** the `→ filed` precondition check happens just before the atomic status
> flip, so authorization could in principle lapse between the check and an actual outbound
> notice. `filed` is an internal state here (no notice leaves the building), but the Slice 8
> send/approval path MUST re-verify active authorization + supported claim at send time, in the
> same transaction as recording the send — not rely on the `filed` transition's earlier check.
