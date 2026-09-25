# ADR 0007: Matching & the review inbox (Slice 5)

Status: accepted. Context: `docs/specs/review.md`.

## Decisions

1. **"Match" = a scored discovery candidate.** Rather than a separate `matches` table, Slice 5
   adds scoring/review columns to `discovery_candidates` (`score`, `score_breakdown`,
   `best_match_asset_id`, `review_status`, …). The domain model's `Match → Case` edge is
   preserved conceptually; a `Case` stub links back to the candidate.

2. **Scoring is config-driven.** pHash / embedding thresholds, score weights, the leak/tube
   **domain list** and the **risky-keyword list** live in `Settings.review_*` (env), not in
   code, so ops can tune them without a deploy. Strongest visual signal wins (max of pHash and
   embedding points, no double-count); rules add on top; total clamped to 100.

3. **Allowlist runs at scoring time, before the inbox.** A match → `auto_dismissed` +
   `dismiss_reason=allowlisted` + a system `ReviewDecision`. `rescore` re-applies the allowlist
   in both directions and never touches human `confirmed`/`dismissed` rows.

4. **Decisions are race-safe.** Confirm/dismiss/reopen flip state with a conditional
   `UPDATE ... WHERE review_status='pending'`; the loser gets a 409. No two reviewers can create
   two cases for one candidate. Confirm **re-checks** enforceability + claim support at confirm
   time (not what the inbox rendered).

5. **Labels are decoupled from candidates.** `review_decisions` keeps snapshot columns and a
   SET NULL FK so training data survives candidate/thumbnail cleanup. `allowlisted` is a
   system-only reason; humans can't pick it.

6. **Guards protect evidence.** A `confirmed` case blocks (a) deleting the matched asset
   (`can_delete_asset` → 409) and (b) purging the referenced candidate/thumbnail in the
   retention job.

7. **Reviewer safety in the UI.** Found thumbnails are blurred by default (per-reviewer
   `staff.review_keep_blur`), click-to-reveal, signed-URL only; static images only (no
   autoplay); external links use `rel="noopener noreferrer"`.

## Not done here

Case lifecycle/state machine (Slice 6), evidence capture (Slice 7), notice generation (Slice 8),
the classifier that consumes the labeled decisions.
