# Spec: Rights, Consent & Agent-Authorization (Slice 2)

Status: implemented in Slice 2. Source of truth for the legal-basis records and the
per-subject claim-support derivation. Behaviour changes must update this file in the same PR.

## Goal

Record, per subject, the legal basis for enforcement — rights records, consent records, and
agent-authorization records — and derive which claim types are currently supported (from
`docs/legal/claims-matrix.md`, still **`unapproved` — draft, pending counsel**). Nothing may
be treated as enforceable without an active agent authorization; no biometric feature may run
without an active biometric consent record.

## Roles

- **admin + reviewer** (with workspace access): create rights/consent records; upload/download
  documents; view everything, including claim support.
- **admin only**: revoke a rights record, revoke a consent record, and create/revoke agent
  authorizations — these change enforceability or trigger the biometric purge.
- Every route is behind `require_workspace_access` (Slice 0) before a tenant session opens.

## Data model (tenant schema, per workspace)

### `rights_records`
`id`, `subject_id`→subjects.id, `type` (`management_agreement` | `photographer_license` |
`copyright_registration` | `self_owned_declaration` | `other`), `grants_enforcement_right`
(bool, default false), `file_key`, `file_name`, `content_type`, `rights_date` (date, null),
`expires_on` (date, null), `coverage` (text), `notes` (text), `status` (`active` | `expired`
| `revoked`, default `active`), `revoked_reason`, `revoked_at`, `revoked_by_staff_id`,
`created_at`.

A rights record **counts toward claim support only** when `status == active` AND
(`expires_on` is null OR `expires_on >= today`).

### `consent_records`
`id`, `subject_id`, `type` (`enforcement` | `biometric`), `file_key`, `file_name`,
`content_type`, `signer_name`, `signed_date` (date), `status` (`active` | `revoked`),
`revoked_reason`, `revoked_at`, `revoked_by_staff_id`, `created_at`.

### `agent_authorizations`
`id`, `subject_id` (**nullable**: null ⇒ workspace-level, set ⇒ subject-level), `file_key`,
`file_name`, `content_type` (all nullable — attestation allowed, no file required),
`signer_name`, `authorized_date` (date), `status` (`active` | `revoked`), `revoked_reason`,
`revoked_at`, `revoked_by_staff_id`, `notes`, `created_at`.

All three are tenant tables with an isolation test each. FKs to `subjects` are within the
tenant schema.

## Documents & storage

- Behind a `Storage` interface. Dev/tests use **MinIO**; production uses **Cloudflare R2**
  (`vg-assets` bucket). Both are S3-compatible; one `S3Storage` (boto3) serves both.
- **Object keys** are tenant-scoped and unguessable: `{ws_schema}/{kind}/{uuid4hex}.{ext}`
  (kind ∈ `rights` | `consent` | `authorization`).
- **Uploads**: rights + consent require a file; authorization file is optional. Allowed types
  are **PDF, JPEG, PNG only**, verified by **magic-byte sniffing** (not the extension/declared
  type). Bodies are read in capped chunks; over `STORAGE_MAX_UPLOAD_BYTES` (~15 MB) → 422.
- **Downloads**: never a public URL. `GET …/file` checks workspace access + record existence,
  then returns a **short-lived presigned GET URL** (`STORAGE_SIGNED_URL_TTL_SECONDS`, ~300 s,
  `Content-Disposition: attachment`). Issuing a URL audits `document.downloaded`.

## Claim-support derivation

Baseline for **every** claim type: an **active agent authorization** covering the subject
(a workspace-level authorization, or a subject-level one for this subject). This is the
enforceability gate — no active authorization ⇒ nothing is supported.

| Claim | Additionally requires |
|---|---|
| `copyright` | ≥1 counting rights record proving ownership: `self_owned_declaration`, `copyright_registration`, or a `photographer_license` with `grants_enforcement_right == true`. A `management_agreement` grants representation, not ownership, and never supports copyright; nor does `other`. |
| `likeness` | active `enforcement` consent |
| `ncii` | active `enforcement` consent |
| `impersonation` | active `enforcement` consent |
| `trademark` | a trademark registration record — not modeled in People-mode Slice 2 ⇒ always unsupported (Brands mode, Phase 2) |

`claim_support(subject)` returns per claim `{claim_type, supported, missing: [reasons]}`.
`subject_enforcement(subject)` returns `{enforceable, active_authorization}` — the gate future
filing slices must call before treating a subject as enforceable.

## Biometrics (independent of claim support)

`biometrics_blocked == false` (a residence/geo check, CLAUDE.md #9) **never implies biometric
consent.** Biometric features (face templates/matching, Slice 3+) require **both**:
1. an **active `biometric` consent record**, AND
2. `biometrics_blocked == false`.

`biometric_features_enabled(subject)` returns that conjunction. The UI states this explicitly.

### Consent revocation → biometric purge (CLAUDE.md #1)
Revoking a **biometric** consent record hard-deletes that subject's face templates/embeddings
via `purge_biometric_data(subject_id)` and audits `biometrics.purged`. Those tables don't
exist yet (Slice 3+), so the hook deletes nothing today — but it is wired and tested now.
Revoking an **enforcement** consent does not trigger a purge.

## Audit

Every mutation writes one `audit_log` row (tenant schema): `rights.created`, `rights.revoked`,
`consent.created`, `consent.revoked`, `authorization.created`, `authorization.revoked`,
`document.uploaded`, `document.downloaded`, `biometrics.purged`.

## Isolation & tests

- Isolation test per new tenant table.
- Upload sniffing (accept PDF/JPEG/PNG, reject disguised/other + oversized), signed-URL access
  (403 without workspace access; URL + audit with access), full claim-support matrix (incl.
  management-agreement-alone unsupported, license flag, expired/revoked exclusion), biometrics
  gating, the biometric-revoke purge hook, admin-only role checks, and audit coverage.
