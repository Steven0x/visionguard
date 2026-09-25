# Spec: Matching & the review inbox (Slice 5)

Status: draft. Turns Slice 4 discovery **candidates** into scored **matches** and gives
reviewers an inbox to Confirm (→ a case stub) or Dismiss (→ a labeled example). "Match" in
the domain model (`Match → Case`) is represented in Phase 1 by a **scored discovery
candidate** — no separate `matches` table.

Non-negotiables in play: **allowlist first** (CLAUDE.md #8), **a human approves every filing**
(#3 — here a human makes every case-creating decision), **every case has a claim** (#4 — a
case stub can't be created without a supported `claim_type`), **tenant isolation** (#5),
**minimize sensitive data** (#7 — found thumbnails stay blurred by default, private,
signed-URL only).

## Scoring

Scoring runs at candidate creation (`apply_scoring`) and on demand (`rescore`). Thresholds,
score weights, the **risky-keyword list** and the **leak/tube domain list** all come from
config (env), never hard-coded — see `Settings.review_*`.

### Image candidates (have `sha256` / `phash` / `embedding`)
Scored against the subject's **ready** assets, strongest signal wins:
1. **pHash Hamming distance** (exact / near-copy): 64-bit hex → int → popcount(xor). Distance
   ≤ `review_phash_exact_max` → exact (`review_score_visual_exact`); ≤ `review_phash_near_max`
   → near (`review_score_visual_near`).
2. **pgvector cosine similarity** (crops / edits): `1 - Asset.embedding.cosine_distance(...)`,
   best-matching ready asset. sim ≥ `review_embedding_match_threshold` →
   `round(review_score_embedding_max * sim)`.
3. **Rules**: source host in the **leak/tube domain list** → `review_score_leak_domain`;
   **risky keywords** (`leaked`, `free`, `onlyfans`, …) in URL / title / page URL →
   `review_score_risky_keyword` each, capped at `review_score_risky_keyword_cap`.

`visual = max(phash_points, embedding_points)` (no double-count); `best_match_asset_id` is the
asset behind the winning visual signal. `score = min(100, visual + rule_points)`. The
`score_breakdown` JSON records each component with the winning asset / distance / similarity.

### Link candidates (no fingerprint)
**Rules only.** `score = rule_points`; breakdown carries `unverified: true` and the inbox
labels them **"unverified — needs manual check."**

### Allowlist (Slice 1) — before the inbox
Every candidate's source/page URL is checked against the workspace allowlist
(`domain` / `url` / `handle` / `account`) at scoring time. A match →
`review_status = auto_dismissed`, `dismiss_reason = allowlisted`, and a **system**
`ReviewDecision` (decided_by = null). Allowlisted candidates never appear in the inbox.
`rescore` **re-applies the allowlist**: a newly-allowlisted pending candidate is auto-dismissed;
an `auto_dismissed` candidate whose allowlist entry was removed returns to `pending`. Human
`confirmed` / `dismissed` decisions are never touched by rescore.

## Data model

**`discovery_candidates` (altered):** `title`, `review_status`
(`pending|confirmed|dismissed|auto_dismissed`, default `pending`), `score` (0–100, null until
scored), `score_breakdown` (JSONB), `best_match_asset_id` (FK assets, SET NULL), `matched_at`,
`dismiss_reason`. Index on `review_status`.

**`cases` (new, stub — full lifecycle is Slice 6):** `subject_id` FK, `candidate_id` FK (SET
NULL; the retention guard prevents deleting a referenced candidate), `matched_asset_id` FK (SET
NULL), `claim_type`, `status` (default `confirmed`), `opened_by_staff_id` (plain int), stamps.

**`review_decisions` (new — labeled training examples, must survive candidate cleanup):**
`candidate_id` FK (SET NULL) + snapshot `subject_id`, `decision` (`confirm|dismiss|reopen`),
`reason`, `claim_type`, `score`, `note`, `decided_by_staff_id` (null = system), `decided_at`.

**`staff` (public, altered):** `review_keep_blur` bool default `true`.

## API (`/workspaces/{id}`, admin + reviewer unless noted)

- `GET /review/inbox?subject_id&min_score&provider&domain&kind` — **pending only**,
  cross-subject, score desc. Each item: score + breakdown, best-match asset summary, source /
  page URLs, **suggested claim** (first supported claim by priority, else `null` → UI shows
  "not supported") + the supported set, `unverified` flag.
- `POST /review/candidates/{cid}/confirm {claim_type}` — **re-checks enforceability + claim
  support at confirm time** (not what the inbox showed). Atomic **conditional update**
  `WHERE review_status='pending'`; the loser of a race gets **409**. Creates a `confirmed`
  case linking candidate + matched asset; `ReviewDecision(confirm)`; audit `review.confirm` +
  `case.created`.
- `POST /review/candidates/{cid}/dismiss {reason}` — reason ∈ {`not_a_match`, `licensed`,
  `fair_use`, `own_account`, `other`}; **humans cannot pick `allowlisted`** (system-only, 422).
  Conditional update `WHERE review_status='pending'`; loser → 409. `ReviewDecision(dismiss)`;
  audit `review.dismiss`.
- `POST /review/candidates/{cid}/reopen {note}` — **admin**. Returns a `dismissed` /
  `auto_dismissed` candidate to `pending` (required `note`). `ReviewDecision(reopen)`; audit
  `review.reopen`.
- `POST /review/bulk-dismiss {domain?|account?, reason, dry_run}` — **dry_run=true returns the
  match count and applies nothing**; capped at `review_bulk_dismiss_max` (500) per call;
  `allowlisted` reason forbidden. audit `review.bulk_dismiss`.
- `POST /review/rescore` — **admin**. (Re)scores pending / auto_dismissed candidates
  (workspace or one subject); re-applies the allowlist. audit `review.rescore`.
- `GET /review/candidates/{cid}/found-thumbnail` · `/asset-thumbnail` — signed URLs (not
  audited). `GET /review/cases` — list stubs.
- `GET|PUT /me/review-prefs {keep_blur}` — per-reviewer blur preference.

## Reviewer safety (frontend)

Found thumbnails are **blurred by default, click to reveal**; a per-reviewer setting
(`review_keep_blur`, default on) keeps blur on so reveals don't persist. **No autoplay** — the
inbox renders static images only (no `<video>`/audio). Source/page links open with
`target="_blank" rel="noopener noreferrer"`. **J/K** move, **C** confirm (claim picker limited
to the supported set), **D** dismiss (reason picker). Bulk dismiss by domain/account shows the
dry-run count before applying.

## Guard hooks (filling the Slice 3 stubs)

- `can_delete_asset` → **False** if a `confirmed` case references the asset
  (`matched_asset_id`); `delete_asset` then raises → **409**.
- **Candidate-retention guard:** `cleanup_expired_thumbnails` skips any candidate referenced by
  a confirmed case (thumbnail + row retained as evidence). Shared helper
  `candidate_referenced_by_confirmed_case`.

## Out of scope (later slices)

Case state machine / timeline / grouping-by-offender (Slice 6); evidence capture (Slice 7);
claim notice generation + filing (Slice 8). Slice 5 only **stores** labeled decisions; the
XGBoost classifier that consumes them is later.
