# Spec: Claims & the notice generator (Slice 8)

Status: draft. This slice turns a **confirmed** case into an approved, counsel-cleared
**notice** that goes out through the right channel, is **sealed write-once**, and moves the
case to `Filed` — or, for form/portal platforms, a copy-ready **packet** that staff submit by
hand and then record (ticket + screenshot, sealed like manual evidence). It is the enforcement
act that Slices 1–7 lead up to.

Non-negotiables in play:
- **#3 a human approves every filing.** A notice cannot be sent without a recorded human
  approval (`approved_by_staff_id`, `approved_at`); send **re-verifies** the whole gate at send
  time, in the same transaction that records the send — it never trusts the earlier `→ filed`
  check (see the Slice-8 note in `docs/specs/cases.md`).
- **#4 every case has a supported claim.** Channel routing obeys `docs/legal/claims-matrix.md`.
  A `trademark` or `likeness` claim can **never** be routed to a DMCA/email channel — enforced
  in the seed, in `route_for`, and tested.
- **#5 tenant isolation.** `notices`, `notice_versions`, `filing_log` are tenant tables with
  isolation tests. Channels + templates are **global public reference data** (see ADR 0011).
- **#6 the sent notice is immutable.** The exact rendered text + recipients + headers are
  sealed via the Slice-7 evidence machinery (`CaptureKind.notice`): SHA-256 manifest, RFC 3161
  timestamp, object-locked write-once bucket, chain-of-custody. Web-form screenshots seal the
  same way as manual evidence.
- **#7 CSAM.** Hand-submitted proof screenshots pass the `CsamScanner` gate (`scan_image`)
  before anything is sealed, exactly like manual evidence upload.
- **Audit** on every draft / edit / approve / send / hand-submission / withdraw.

See ADR `docs/adr/0011-notices-channels-templates.md`.

## Nothing sends yet — by design

Every template ships `unapproved`, and the claims matrix banner
(`docs/legal/claims-matrix.md`) is still `unapproved`. **Sending refuses on an unapproved
template.** Until counsel reviews the matrix and an admin marks templates `counsel_approved`,
the product can draft and render notices but **cannot send a single one**. That is the intended
Phase-1 safety posture, not a gap.

## Channel registry (global, `public` schema)

`channels` maps **platform → claim_type → method → destination → required fields**:

- `method` ∈ `email` | `web_form` | `portal`.
  - `email` → a notice is **rendered, sent via SendGrid (or the outbox), and sealed**;
    `destination` is the DMCA-agent / abuse email.
  - `web_form` / `portal` → **no send**. We produce a copy-ready **packet + checklist**;
    `destination` is the form URL. Staff submit by hand, then record the ticket + a screenshot.
- `required_fields` (JSONB) — context keys the notice/packet must contain for that channel.
- **Matrix conformance:** a row may only pair a platform with a claim type the matrix allows,
  and **only the matrix's allowed method** — no `email`/DMCA destination for `trademark` or
  `likeness`. A validated seed helper asserts each row; `route_for` re-checks at runtime.

Seeded (from `ops/RUNBOOK_day1.md`): Instagram, Facebook, TikTok, X, Google Search (delist),
and a `generic_host` DMCA-email fallback (footer/WHOIS abuse contact). `copyright` uses
DMCA/email or copyright web forms; `trademark`/`likeness`/`impersonation`/`ncii` use platform
web forms only.

## Notice templates (global, `public` schema)

`notice_templates`: one per `(claim_type, method)`, with a `subject_template`, a
`body_template` (with `{{whitelisted_field}}` placeholders), and `required_elements` (JSONB —
the claims-matrix elements the notice must contain, e.g. the six DMCA §512(c)(3) items).

Approval lifecycle:
- Every template starts **`unapproved`**.
- Only an **admin** may `counsel_approved` a template; doing so records `approved_by_staff_id`,
  `approver_name`, and `approved_at` **on the row** (the durable approval record — `audit_log`
  is tenant-scoped, so a public action records on-row + app log, per ADR 0011).
- **Editing a template body bumps `version` and resets it to `unapproved`.** An approved
  template can never be silently altered.

## Rendering & injection guards (`services/notice_render.py`)

- `build_context(...)` assembles a **whitelisted** field dict from case data: subject legal
  name, agent/authorization signer, contact email, infringing URLs, work description, evidence
  SHA-256 + capture time, and the good-faith / penalty-of-perjury statements.
- `render(template, context)` replaces **only known `{{key}}` tokens**; an unknown token is an
  error. No expression evaluation, no attribute access (no Jinja2 / no SSTI surface). Notices are
  plain text (no markup sink), so values are substituted verbatim; the header fields are
  CR/LF-sanitized below.
- `sanitize_header_value(...)` strips CR/LF and header-injection characters. Applied to every
  recipient, reply-to, and subject — for both rendered output **and user-edited drafts**.
- `check_required_elements(...)` — a draft missing any of the template's `required_elements`
  or the channel's `required_fields` is renderable but **incomplete** (un-sendable).

## Draft → review → approve → send (`services/notices.py`, the only mutator)

```
(case Confirmed) → create_draft → [edit_draft]* → approve → send ─┬─ email: send + seal → case Filed
                                                                   └─ web_form/portal: packet → record_hand_submission (scan+seal) → case Filed
notice: draft ───────────────────────────────────────────────────────────────────────────────→ sent
sent → withdraw (note) → withdrawn   (case Filed → Withdrawn; re-file via cases.refile)
```

- `create_draft(case, platform)`: case must be **`confirmed`**; `route_for` picks the channel;
  the `(claim_type, method)` template renders **v1**; writes `notices` (`draft`) +
  `notice_versions` v1; audit `notice.drafted`.
- `edit_draft(notice, subject, body)`: sanitize; append a **new `notice_versions` row**, bump
  `current_version`; audit `notice.edited`.
- `approve(notice, approved_by)`: records `approved_by_staff_id` + `approved_at`; audit
  `notice.approved`.
- `send(notice)` — **the guarded choke point (`send_blockers`, re-checked at send time):**
  1. case still **`confirmed`**;
  2. **active authorization** (`active_authorization`) and **claim still supported**
     (`claim_support`);
  3. a **fresh sealed evidence capture** exists (`has_fresh_sealed_capture`);
  4. the **channel method is still matrix-allowed** for the claim (`method_allowed_for_claim`) —
     defense-in-depth so a channel row flipped to a forbidden method can't send;
  5. the template is **`counsel_approved`** (else refuse — this is why nothing sends today);
  6. the notice was **approved by a human** *and the approval covers the current version*
     (`approved_version == current_version` — an edit after approval requires re-approval, so no
     one approves v1 and sends v2), and the draft is **complete**.
  Then by method:
  - **`email`**: render + sanitize the final subject/body/headers; `seal_notice_capture`
    (`CaptureKind.notice`, artifacts `notice.txt` + `meta.json`) seals the exact text +
    recipients + headers; set `notices.status=sent`, `sealed_capture_id`, `sent_by/at`; write
    `filing_log` (`sent`); move the case **`confirmed → filed`** via `cases.transition`; audit
    `notice.sent`; **commit** — so the send is durably recorded *before* the transport. The
    email backend send is the **last** step: the case transition re-checks filing preconditions
    atomically (a concurrent case move raises before anything is sent), and committing first
    means a transport failure can neither roll back the record nor double-send (a retry is
    refused — the notice is no longer a draft).
  - **`web_form`/`portal`**: `send` produces the **packet** (rendered fields + checklist +
    destination URL) and marks the notice **awaiting hand-submission** (stays `draft` until
    recorded — nothing left the building). `record_hand_submission(notice, ticket, screenshot)`
    runs the **CSAM gate** then `seal_manual_upload` on the screenshot, writes `filing_log`
    (`submitted_by_hand`, ticket), sets `notices.status=sent`, moves the case to `filed`;
    audit `notice.hand_submitted`.
- `withdraw(notice, note)`: note required; `cases.transition(filed → withdrawn)`;
  `notices.status=withdrawn`; `filing_log` (`withdrawn`); audit `notice.withdrawn`. To correct a
  wrong claim, withdraw then **re-file** a new case via the existing `cases.refile`.

## Data model

### Public schema (migration `0014_public`)
- **`channels`**: `id`, `platform`, `claim_type`, `method`, `destination`, `required_fields`
  (JSONB), `notes`, `active`, `created_at`. Unique `(platform, claim_type)`.
- **`notice_templates`**: `id`, `claim_type`, `method`, `name`, `subject_template`,
  `body_template`, `required_elements` (JSONB), `approval_status`
  (`unapproved` | `counsel_approved`), `approved_by_staff_id`, `approver_name`, `approved_at`,
  `version`, `created_at`. Unique `(claim_type, method)`.

### Tenant schema (migration `0015_tenant`; isolation tests for all three)
- **`notices`**: `id`, `case_id` (FK), `channel_id`, `template_id`, `template_version`,
  `claim_type`, `method`, `platform`, `destination`, `status` (`draft`|`sent`|`withdrawn`),
  `current_version`, `sealed_capture_id` (FK `evidence_captures.id`, set on send),
  `created_by_staff_id`, `approved_by_staff_id`, `approved_at`, `sent_by_staff_id`, `sent_at`,
  `created_at`. Public Staff ids carried as plain ints (no cross-schema FK, like `cases`).
- **`notice_versions`** (append-only; trigger + REVOKE, like `case_notes`/`custody_events`):
  `id`, `notice_id` (FK), `version`, `subject`, `body`, `edited_by_staff_id`, `created_at`.
- **`filing_log`**: `id`, `case_id`, `notice_id`, `platform`, `claim_type`, `method`,
  `outcome` (`sent`|`submitted_by_hand`|`withdrawn`), `ticket_number`, `response`,
  `filed_by_staff_id`, `created_at`.

The sealed sent notice reuses `evidence_captures` with **`CaptureKind.notice`** — no new
evidence table.

## API (`/workspaces/{id}`, admin+reviewer unless noted)
- `GET  /cases/{cid}/notice` — current notice + versions + completeness + `can_send` reasons.
- `POST /cases/{cid}/notice` — create draft (body: `platform`).
- `PUT  /cases/{cid}/notice` — edit draft (subject, body) → new version.
- `POST /cases/{cid}/notice/approve` — record human approval.
- `POST /cases/{cid}/notice/send` — send (email) or produce packet (web_form/portal).
- `GET  /cases/{cid}/notice/packet` — copy-ready packet + checklist (web_form/portal).
- `POST /cases/{cid}/notice/hand-submission` — multipart: ticket_number + screenshot.
- `POST /cases/{cid}/notice/withdraw` — note required.
- `GET  /workspaces/{id}/filing-log` — filing log (filter by platform).
- Global reference (**admin-only**): `GET /channels`, `GET /notice-templates`,
  `PUT /notice-templates/{id}` (edit → new version, resets to unapproved),
  `POST /notice-templates/{id}/approve`.

Errors: forbidden matrix routing → 422; unapproved/unapproved-template/stale-auth/stale-claim/
no-fresh-evidence/not-approved/incomplete at send → 422; case not `confirmed` → 409/422.

## Email (`api/app/email/`)
`EmailBackend` protocol; `SendGridBackend` (prod) and `OutboxBackend` (dev/test — captures,
never sends). Factory `get_email_backend()` off config, like `get_evidence_storage()`. Config:
`email_backend` (`outbox` default | `sendgrid`), `sendgrid_api_key`, `email_from`,
`email_reply_to`, `email_rate_limit_per_min`. A config guard **refuses `sendgrid` unless
`is_production`** — dev/test can never send real mail — and requires `sendgrid_api_key` +
`email_from` when it is selected.

## Matrix-required send-time guards (enforced in code)

Beyond the six gate items above, these matrix preconditions are hard-enforced (not deferred):

- **Fair-use consideration** (*Lenz*) before a `copyright` filing: the approver must tick "I
  considered fair use", stored on the notice (`fair_use_considered`) bound to the approved
  version and reset by any edit; `send_blockers` refuses a copyright send without it.
- **Allowlist re-check at send** (CLAUDE.md #8): `send_blockers` re-runs the workspace allowlist
  against both the case's `source_url` and `page_url` (the same URLs intake checked). A source
  allowlisted after the case opened (newly authorized reseller / the subject's own account)
  blocks the send.
- **Identity verification for `likeness`/`ncii`/`impersonation`** (Phase 2 liveness/ID) does not
  exist yet, so **approving a template for those claims is refused** (`approve_template` →
  `TemplateApprovalBlocked`). They therefore can never reach a sendable state until the gate
  ships. Only `copyright` templates can be counsel-approved in Phase 1.

## Out of scope (later)
Outcomes / re-check / re-upload watch (Slice 9); reports & metrics (Slice 10); automated
web-form submission; demand letters & recovery; Brands-mode `trademark` support (needs a
trademark-registration rights record, incl. a registration-number notice element); the actual
identity-verification gate that would unblock `likeness`/`ncii`/`impersonation` template
approval (Phase 2).
