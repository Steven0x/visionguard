# ADR 0011: Notice channels, templates, and the send/seal path (Slice 8)

Status: accepted (2026-09-27)

## Context

Slice 8 turns a confirmed case into an approved notice that goes out through the right channel,
is sealed, and moves the case to `Filed`. We had to decide where channel/template reference
data lives, how the sent notice is made immutable, how email sending is kept safe in dev/test,
and how notices are rendered without opening a template-injection hole.

## Decisions

### 1. Channels and templates are global `public`-schema reference data

The channel registry and notice templates are VisionGuard-wide, not per-tenant. Phase 1 is an
internal concierge tool: VisionGuard staff serve every agency and **counsel approves each
template once** for all of them. Duplicating them per tenant would force re-approval per
workspace and drift. They live in `public` alongside `staff`/`workspaces`.

Consequence: a template approval is a **global** admin action, but `audit_log` is
tenant-scoped. We therefore record the approval **on the template row** (`approved_by_staff_id`,
`approver_name`, `approved_at`) — that on-row record is the durable proof — plus an application
log line. Tenant `audit_log` still records every per-case notice action (draft/send/withdraw).
`notices`/`notice_versions`/`filing_log` remain tenant tables with isolation tests.

### 2. The sent notice is sealed by reusing the Slice-7 evidence machinery

Rather than a parallel immutable store, the exact sent notice (rendered text + recipients +
headers) is sealed with a new `CaptureKind.notice` through the existing `_seal` path: SHA-256
manifest, RFC 3161 timestamp, object-locked write-once bucket, and a chain-of-custody row. This
inherits every CLAUDE.md #6 guarantee for free and keeps one verification/export path
(`vg verify-evidence`). Web-form proof screenshots reuse `seal_manual_upload` unchanged.

### 3. Email has `sendgrid`/`outbox` backends; dev/test can never send real mail

`get_email_backend()` mirrors `get_evidence_storage()`/`get_csam_scanner()`. `OutboxBackend`
(default) captures messages and never touches the network. A config `model_validator`
**refuses `email_backend=sendgrid` unless `is_production`** (the same guard shape as the fake
CSAM/auth-bypass guards), and requires `sendgrid_api_key` + `email_from` when selected. So a
misconfigured dev/test deploy fails to start rather than sending real notices.

### 4. Safe minimal renderer, not Jinja2

Templates render via a whitelisted `{{key}}` substitution over a fixed context dict, with no
expression evaluation and no attribute access. Notices are plain text (no HTML/markup sink), so
values are substituted verbatim; the injection surface is the email headers, which are
CR/LF-sanitized. This avoids a new dependency
(CLAUDE.md "ask before adding a dependency") and removes the SSTI surface a full template engine
would add. All recipient/subject/header values are additionally CR/LF-sanitized, for both
rendered output and user-edited drafts, to block header/recipient injection.

## Consequences

- Counsel approves templates once; nothing sends while they are `unapproved` (intended Phase-1
  posture) — the whole claims matrix is still `unapproved`.
- `route_for` and the seed both enforce matrix conformance (no DMCA for trademark/likeness).
- Global reference data means no per-tenant isolation test for `channels`/`notice_templates`;
  the tenant notice tables are isolation-tested as usual.
- The send path re-verifies authorization + supported claim + fresh evidence + template
  approval + human approval at send time, in the same transaction as recording the send.
