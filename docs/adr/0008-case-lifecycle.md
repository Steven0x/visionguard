# ADR 0008: Case lifecycle & state machine (Slice 6)

Status: accepted. Context: `docs/specs/cases.md`, CLAUDE.md "Domain model".

## Decisions

1. **The case service is the sole mutator of `status`.** Every transition validates against a
   single `TRANSITIONS` table, uses a conditional `UPDATE ... WHERE status=<from>` (race loser
   → 409), and writes a `case_event` + audit entry. Routers never set `status`.

2. **State machine (amended from the original CLAUDE.md set):**
   - Added terminal **`withdrawn`**: `filed → withdrawn` (**note required**) retracts the filed
     notice. It is **not** a removal.
   - **`countered` is not terminal**: `countered → escalated | closed`.
   - `TERMINAL = {dismissed, withdrawn, recovered, closed}`.

3. **Correcting a wrong claim after filing does NOT route through `removed`/`monitoring`.**
   That would record a false `removed` transition and corrupt removal-rate / time-to-removal
   metrics. Instead: `filed → withdrawn`, then **`refile`** opens a *new* case from the same
   candidate under the corrected claim. The duplicate-open-case check ignores terminal cases,
   so the withdrawn case never blocks the re-file; the two cases carry reciprocal `link` events.
   `claim_type` is otherwise editable only in `discovered`/`confirmed` and locked once `filed`.

4. **Metrics (Slice 10) count only real `removed` transitions** (derived from `case_events`);
   `withdrawn` cases are excluded from the removal-rate denominator and reported separately.

5. **`→ filed` re-checks preconditions at transition time** (active authorization + still-
   supported claim), never trusting earlier inbox state. `requires_evidence_pack(case)` is a
   documented placeholder returning `True` in Phase 1; **Slice 7** replaces its body with the
   real immutable-`EvidencePack` check — this is the single choke point for that gate.

6. **Duplicate protection:** a partial unique index `(subject_id, source_key) WHERE status NOT
   IN (terminal)` plus a service-level check → no two *open* cases for one subject + canonical
   URL. Terminal cases are ignored (so re-file works).

7. **Follow-up timers are config-driven** (`case_due_days` per state); overdue = open ∧
   `due_at < now`. Offender grouping via a documented `offender_key(url)` heuristic
   (platform+handle / marketplace seller / domain).

## Not done here
Evidence gate body (Slice 7), notice/filing (Slice 8), auto-reopen on reappearance + timer
firing/notifications + metrics computation (Slices 9–10).
