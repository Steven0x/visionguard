# ADR 0012: Outcomes, the URL re-check, and reopen-on-reappearance (Slice 9)

Status: accepted (2026-09-27)

## Context

Slice 9 closes the enforcement loop after a notice is filed: record the platform's response,
chase overdue filings, watch the URL to detect a real take-down, cycle removed cases through a
Monitoring window, and reopen a monitored case when the same infringement comes back — without
adding any case state and without letting automation transition a case on its own.

## Decisions

### 1. Outcomes are records layered on the existing state machine

An outcome (`removed | rejected | countered | no_response`) is recorded on a filed notice. Only
`removed` (`filed → removed`) and `countered` (`filed → countered`) move the case; `rejected`
and `no_response` are pure records that keep the case `Filed` and reset the follow-up timer. This
avoids new states (`rejected`/`no_response` would have been dead-end synonyms for "still filed")
and reuses the existing `filed → escalated` (re-file) and `filed → withdrawn` (wrong claim) exits.

### 2. Outcomes are append-only; corrections supersede

`notice_outcomes` is append-only (trigger + REVOKE, like `notice_versions`). A mistaken outcome
is corrected by appending a superseding row (`supersedes_id`), never by editing — the platform
response history stays intact and auditable. The **latest non-superseded** row per notice is the
effective outcome.

### 3. Metrics count filings (notices), not cases

A case can be filed, removed, reopened, and re-filed. Counting per case would hide re-offences
and double-removals. Removal rate = `removed / (filed − withdrawn)` per `(platform, claim_type)`
with `withdrawn` excluded from the denominator and reported separately (per the cases spec), and
the **still-pending** count reported so young filings are visible. Time-to-removal uses the
outcome's staff-entered **`effective_at`** (when the content actually went down), not the
confirmation timestamp, so a late confirmation doesn't inflate the metric.

### 4. The URL re-check proposes; a human confirms; nothing auto-transitions

A daily beat probes each open filed/monitoring case's URL through the existing SSRF-safe fetcher
and appends a `url_rechecks` row. It only ever sets a proposal flag on the case
(`removal_proposed_at` / `reappearance_proposed_at`); a human confirms (which seals the removal
proof) or dismisses. Key judgements:

- **Probe `page_url`, not the CDN `source_url`.** Signed CDN image URLs expire (false `gone`) and
  CDNs keep serving after a page is removed (false `live`). `source_url` is a fallback only when
  `page_url` is null.
- **`live` is never proof.** Many platforms serve `200` for removed content (soft-404s), so a
  standing `live` means nothing and never triggers anything. A removal is proposed only when the
  two most-recent rechecks are both `gone` and ≥24h apart (a single `gone` can be a geo-block,
  login wall, or rate limit). A reappearance is proposed only on a `gone → live` transition.
- **The probe does not download the body.** It reads the HTTP status and closes the stream,
  keeping the SSRF hardening (pinned IP, per-hop redirect re-validation, timeout, redirect cap)
  while adding no new egress surface.

### 5. Reopen instead of duplicate; re-check the same guards; require a fresh approval

When new discovery matches a `monitoring` case for the same subject, `review.confirm_candidate`
reopens that case (`monitoring → discovered → confirmed`, history attached) rather than opening a
duplicate. Reopen re-runs the confirm guards (active authorization/consent, claim support,
allowlist) — a since-allowlisted or now-unauthorized source cannot reopen. Matching is by same
URL, same platform account (`offender_key`), or same host + same matched asset **only for
non-platform hosts** — domain-alone never merges two different posts on the same platform. A
reopened case starts a **new filing cycle**: the prior notice's approval is never reused, so a
fresh draft and a fresh human approval are required before it can be filed again (`create_draft`
refuses only when an *active* draft already exists).

### 6. The Monitoring tail is system housekeeping

`removed → monitoring` (after the proof seals) and `monitoring → closed` (after the watch window)
run on a daily beat with a `None` actor, audited. This is internal bookkeeping — nothing goes
outbound — so CLAUDE.md #3 (a human approves every *filing*) is not implicated.

## Consequences

Two new tenant tables (`notice_outcomes`, `url_rechecks`) with isolation tests; two nullable
proposal columns and a nullable `response_window_days` on the global channel row. The metrics
service is the computation Slice 10's reporting/UI will build on.
</content>
