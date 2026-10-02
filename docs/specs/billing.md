# Spec: Billing (Slice 13)

Status: draft. Per-workspace subscription billing for the concierge MVP. **Stripe hosted only** —
Checkout to subscribe/pay, Customer Portal to manage card/ACH/invoices/cancellation. VisionGuard
never touches payment data. Stripe is the **source of truth**; the app keeps a thin, read-only
mirror per workspace and reconciles to Stripe.

See ADR `docs/adr/0016-billing-stripe.md`.

## What this slice is not

No in-app pricing math. All amounts, the volume discount, and annual pricing live on **Stripe Price
objects** referenced by env price IDs; our code only ever sets a subscription **quantity** and
attaches **coupons/credits**. No agency self-signup (staff still provision workspaces and agency
users — Slice 12). No usage metering beyond the per-subject quantity.

## Pricing (config-driven, never hard-coded)

| Plan | Price | Model | Min qty |
| --- | --- | --- | --- |
| Core | $99 / talent / month | per active subject (subscription quantity = active subjects) | 5 |
| Priority | $179 / talent / month | per active subject | 5 |

- **Priority** turns on: impersonation / fake-ad sweeps, faster discovery frequency, weekly reports.
- **Volume:** 15% off at 20+ subjects. Implemented as a Stripe **volume-tier price** (the whole
  quantity is billed at the tier the total lands in): tier 1 `1–19` at full unit price, tier 2 `20+`
  at the 15%-off unit price. Chosen over graduated because "15% off when you reach 20" means every
  subject gets the discount, which volume tiering expresses directly — and it keeps all money math
  in Stripe.
- **Annual prepay:** 2 months free, modelled as **separate annual Price objects** (one per plan),
  not a code-side calculation.
- **Onboarding audit:** $1,500 one-time **Checkout payment** (`mode=payment`). A staff admin can
  mark it **credited toward the first month** (see below).
- **Design-partner discount:** a Stripe **coupon** (50% off for 3 months) a staff admin applies per
  workspace.

Every price/coupon is an env-configured ID (`.env.example`). Changing a price never requires a
deploy of money logic — only an env change — because the app does not compute amounts.

## Billing mode

`workspace_billing.billing_mode` ∈ `stripe | manual`.

- **`manual`** — invoiced outside Stripe (design partners, demos, legacy). **No billing gates
  apply.** Existing workspaces are migrated to `manual` so nothing breaks on rollout.
- **`stripe`** — subscription billing as described here; the gates below apply.

Only an **admin** changes the mode (audited `billing.mode_changed`). Switching to `stripe` does not
itself create a subscription; the workspace stays `status=none` until Checkout completes.

## Mirror (per workspace, Stripe is source of truth)

`workspace_billing` (public schema, 1:1 with `workspaces`):

| Field | Meaning |
| --- | --- |
| `workspace_id` | PK/FK → workspaces |
| `billing_mode` | `stripe` \| `manual` |
| `stripe_customer_id` | **unique**; one customer per workspace, created server-side before Checkout. Never re-mapped to another workspace. |
| `stripe_subscription_id` | current subscription, if any |
| `status` | `none` \| `trialing` \| `active` \| `past_due` \| `canceled` (mirrors Stripe; `none` = never subscribed) |
| `plan_tier` | `none` \| `core` \| `priority` (derived from the subscription's price ID) |
| `cadence` | `none` \| `monthly` \| `annual` (derived from the price ID) |
| `quantity` | current Stripe subscription quantity (mirror; we re-assert the derived value — see below) |
| `current_period_end` | from Stripe |
| `past_due_since` | first time we observed `past_due`; **never reset on replay/re-fetch**; cleared only when status leaves `past_due`/`canceled` |
| `grace_until` | derived = `past_due_since + billing_grace_days`; stored for display |
| `billing_contact_staff_id` | the one agency user who manages billing from the portal (nullable) |
| `onboarding_credit_applied_at` | set once when the $1,500 audit is credited (idempotent) |
| `design_partner_coupon_applied_at` | set when the design-partner coupon is applied |
| `priority_override` | `NULL` = no override; `true/false` = admin forces priority features on/off |
| `discovery_frequency_override` | `NULL` = none; else an admin-forced max `ScanFrequency` |

`workspaces.plan` stays a free-text **ops label** and is **not** driven by billing. The billing tier
lives only in `plan_tier`.

`billing_events` (public): `stripe_event_id` (**unique**), `type`, `received_at`. The webhook
idempotency ledger.

> **Why public, not tenant:** these rows hold only Stripe IDs and per-workspace plan config — the
> same altitude as the `workspaces` row — and no subject/case/evidence data. So the per-tenant
> isolation-test rule (CLAUDE.md #5) does not apply to them. Audit rows for billing still land in
> the **tenant** `audit_log` for that workspace (via a tenant session), as everywhere else.

## Quantity sync (server-derived, idempotent)

The subscription quantity is **always** `desired = max(active_subject_count, billing_min_quantity)`
(`billing_min_quantity` default 5). It is set **absolutely** (not as a delta), so re-running is a
no-op when already correct; proration uses Stripe defaults.

- Triggered when a subject is **added, archived, or reactivated** (and on CSV import), via a Celery
  task `worker.sync_billing_quantity(workspace_id)` enqueued after the DB change commits. The task
  recomputes `desired` from the live active count and sets it — so a lost/duplicated enqueue cannot
  corrupt the count.
- **No endpoint ever accepts a quantity.** Quantity is only ever the derived value; a client cannot
  manipulate it to underpay.
- **Drift correction (defensive):** any observed subscription quantity that differs from `desired`
  — from a webhook, a re-fetch, or the daily reconciliation — is reset to `desired` in Stripe and
  the mirror, and audited `billing.quantity_corrected` (meta: `{observed, corrected_to}`). A webhook
  reporting quantity 3 is corrected back to `max(active, 5)`.
- Applies only in `stripe` mode with an active/past_due/trialing subscription. `manual`, `none`, and
  `canceled` are no-ops.

## Checkout & Customer Portal (hosted)

- **Create the customer first.** `POST /workspaces/{id}/billing/checkout` (admin) or the portal
  billing-contact route ensures a Stripe **customer** exists for the workspace (unique
  `stripe_customer_id`), then creates a Checkout Session for the chosen plan+cadence price, quantity
  = derived value, `payment_method_types=[card, us_bank_account]` (ACH enabled), `automatic_tax`
  from `stripe_automatic_tax` (default off). Returns the hosted URL.
- **Onboarding audit** is a separate Checkout Session, `mode=payment`, for the audit price.
- **Customer Portal** `POST .../portal` returns a Billing-Portal Session URL for managing
  card/ACH/invoices and **cancellation only**. The portal **configuration disables quantity changes
  and plan switching** (`subscription_update` not enabled / no products listed) — quantity is ours
  to derive and plan changes go through staff. This is set via the Portal **configuration** (API),
  documented here and in `.env.example`, not left to the Stripe dashboard default.

`stripe_automatic_tax` (default `false`) is passed to every Checkout Session. **Enable only after
confirming sales-tax obligations** (nexus/registration); leaving it off avoids collecting tax we are
not registered to remit.

## Webhooks

`POST /billing/webhook` — **unauthenticated but Stripe-signature-gated**. Explicitly added to the
default-deny route-walk allowlist (it has no staff/agency identity by design).

1. **Verify the signature** against `stripe_webhook_secret`. Invalid/missing → **400**, no state
   change.
2. **Idempotent on event id:** if `stripe_event_id` is already in `billing_events`, return 200 and
   do nothing (replay-safe). The event id is recorded **only after** the state has been applied, so
   a mid-processing failure (e.g. a Stripe timeout on the re-fetch) leaves the event unrecorded and
   Stripe's retry reprocesses it rather than being swallowed as a duplicate (apply is idempotent).
3. **Never trust event ordering or payload state.** For any subscription/invoice event we **re-fetch
   the subscription from Stripe** and recompute the mirror from that — so an out-of-order or stale
   event cannot regress newer state.
4. Resolve the workspace from `stripe_customer_id` (our stored mapping). An unknown customer is
   recorded and ignored (never auto-mapped).
5. Record the event id, update the mirror, run drift correction, write audit on the **tenant**
   session.

Handled events: `checkout.session.completed` (subscription → attach subscription + sync; `mode=
payment` → record the onboarding **audit payment**), `customer.subscription.created|updated|deleted`
(re-fetch → mirror; `deleted` → `canceled`), `invoice.payment_failed` (→ `past_due`, set
`past_due_since` if unset), `invoice.paid` (→ clears `past_due`/`past_due_since` when Stripe reports
active).

## Onboarding credit

A staff admin marks the onboarding audit **credited toward the first month**:
`POST /workspaces/{id}/billing/onboarding-credit`. This applies a **real Stripe customer balance
credit** of the **audit price amount fetched from Stripe** (not hard-coded) using a deterministic
idempotency key (`onboarding-credit:{workspace_id}`), so it is applied **at most once per
workspace**. Sets `onboarding_credit_applied_at`, audited `billing.onboarding_credited`
(meta: `{amount}`). Re-invoking is a no-op.

## Non-payment & suspension

Config `billing_grace_days` (default 14). Behaviour by status (stripe mode only):

| Status | Effect |
| --- | --- |
| `active` / `trialing` | normal |
| `past_due` within grace (`now ≤ grace_until`) | **banner only** in staff console + portal; everything works |
| `past_due` past grace (`now > grace_until`) | **suspended** |
| `canceled` | **suspended** (same as past-grace) |
| `none` (stripe mode, never subscribed) | **suspended** |

**Suspended** means exactly two gates, and nothing more:

1. **No new subjects.** `create_subject`, CSV `import_commit`, and `reactivate_subject` call
   `enforce_can_add_subject(workspace_id)` → **402 Payment Required** when suspended.
2. **No new discovery jobs.** `dispatch_scheduled_scans` skips suspended workspaces; `intake_urls`
   (manual + portal tips) raises when suspended.

**Never blocked, ever — tested one by one:** recording outcomes, re-checks on **filed** cases,
withdrawals, evidence access, report generation/download, and portal reads/report downloads. **No
data is ever deleted because of billing.** Suspension is a pause on *new* work, not a teardown.

Feature limits (also mirror-driven, stripe mode):
- **Priority flags** (impersonation/fake-ad sweeps, weekly reports) require effective priority =
  `priority_override` if set, else `plan_tier == priority`.
- **Discovery frequency** is capped by the effective plan: Core cannot run faster than weekly;
  Priority may run daily. `discovery_frequency_override` (admin) overrides the cap. Enforced
  server-side in the discovery dispatcher and the settings-update path, not just the UI.

Admin overrides (`priority_override`, `discovery_frequency_override`) are set via
`POST /workspaces/{id}/billing/override` and audited `billing.override_changed`.

## Daily reconciliation (beat)

`worker.reconcile_billing` runs daily under the same **single-beat + Redis `beat_lock`** pattern as
the other beat jobs. For every `stripe`-mode workspace with a subscription it: re-fetches the
subscription, re-syncs the **quantity** (drift-corrects), refreshes **status**/`current_period_end`/
`past_due_since`, and **logs a structured drift alert** on any mismatch it had to correct. This is
the safety net if a webhook is missed or arrives out of order.

## Billing contact (portal)

One designated **agency user per workspace** is the billing contact
(`billing_contact_staff_id`). Only an **admin** sets it
(`PUT /workspaces/{id}/billing/billing-contact {staff_id}`); the target must be an `agency` user
**of that workspace** (membership-checked), audited `billing.contact_changed`. An agency user can
never promote itself.

Portal:
- `GET /portal/billing` → status/plan/quantity/period-end/grace banner for the agency; whether the
  caller is the billing contact.
- `POST /portal/billing/checkout`, `POST /portal/billing/portal` → hosted URLs, **only** for the
  billing contact (`ctx.staff.id == billing_contact_staff_id`); any other agency user → **403**.
  Non-contacts see "«contact email» manages billing."

## API summary

Staff admin (`require_role(admin)`), under `/workspaces/{id}/billing`:
`GET ` (status) · `POST /checkout` · `POST /portal` · `POST /onboarding-credit` · `POST /coupon`
(design-partner) · `POST /override` · `PUT /billing-contact` · `PUT /mode`.

Unauthenticated, signature-gated: `POST /billing/webhook`.

Agency billing-contact (`get_agency_context`), under `/portal/billing`:
`GET ` · `POST /checkout` · `POST /portal`.

Errors: suspended new-subject/new-discovery → **402**; over nothing here is 429; bad webhook sig →
**400**; unknown Stripe customer → 200 (ignored, recorded); non-contact agency billing action →
**403**.

## Config (`.env.example`)

`BILLING_BACKEND` (`stripe` | `fake`; `fake` dev/test only), `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_CORE_MONTHLY`, `STRIPE_PRICE_CORE_ANNUAL`,
`STRIPE_PRICE_PRIORITY_MONTHLY`, `STRIPE_PRICE_PRIORITY_ANNUAL`, `STRIPE_PRICE_ONBOARDING_AUDIT`,
`STRIPE_COUPON_DESIGN_PARTNER`, `STRIPE_PORTAL_CONFIGURATION_ID` (the portal config that disables
quantity/plan edits), `BILLING_MIN_QUANTITY` (5), `BILLING_GRACE_DAYS` (14),
`STRIPE_AUTOMATIC_TAX` (false).

**Config guard** (mirrors the SendGrid/CSAM guards):
- `BILLING_BACKEND=fake` only when `APP_ENV ∈ {dev, test}`.
- Deployments (`staging`/`production`) require `BILLING_BACKEND=stripe`, a secret key, a webhook
  secret, all plan price IDs, and `STRIPE_PORTAL_CONFIGURATION_ID` (the restricted Customer-Portal
  config that disables self-serve quantity/plan edits — without it Stripe falls back to its default,
  which would let a billing contact change quantity/plan themselves).
- **Production requires live keys** (`sk_live_…` + `whsec_…`); **live keys are refused outside
  production**; **staging must use test keys** (`sk_test_…`). A misconfigured deploy fails to boot.

## Tests

- **Config guard** (`test_billing_guard.py` / extend `test_production_guard.py`): fake outside
  dev/test refused; live key outside production refused; production without live key refused;
  staging with live key refused; deployment missing price IDs refused.
- **Webhook** (`test_billing_webhook.py`): forged/missing signature → 400, no change; replayed event
  id → no double-apply; **out-of-order** event → mirror still correct because we re-fetch;
  **quantity-drift**: webhook reports quantity 3 → corrected to `max(active, 5)` + audit
  `quantity_corrected`; unknown customer → 200, recorded, no mapping; `past_due_since` set once and
  not reset by a replay/re-fetch.
- **Plan-state tampering** (`test_billing_authz.py`): no agency/portal/reviewer route mutates mirror
  fields; only the webhook + admin audited actions do; no endpoint accepts a `quantity`.
- **Quantity** (`test_billing_quantity.py`): add/archive/reactivate + CSV import each drive the fake
  Stripe to `max(active, 5)`; min-5 floor holds; manual/none/canceled are no-ops.
- **Suspension** (`test_billing_suspension.py`): past-due-in-grace = banner only (all work
  proceeds); past-grace and canceled and stripe-none each block new subject (402) + new discovery,
  **but** outcomes, filed-case recheck, withdrawal, evidence read, report download, and portal
  report download all still succeed; nothing is deleted.
- **Billing contact** (`test_billing_contact.py`): only admin sets it; target must be an agency user
  of that workspace; non-contact agency billing action → 403; escalation impossible.
- **Feature limits** (`test_billing_features.py`): Core capped to weekly; priority/override allow
  daily + sweeps; override audited.
- **Onboarding credit**: applied once (idempotency key), amount from the audit price, audited;
  re-invoke is a no-op.
- **Reconciliation** (`test_billing_reconcile.py`): a drifted subscription is re-synced + logged;
  single-beat lock respected.
- **Audit**: plan/quantity/coupon/credit/override/contact/mode changes each write an audit row.
- **Default-deny** route walk stays green with `/billing/webhook` allowlisted.
- **Frontend** vitest: the billing contact sees portal billing actions; a non-contact agency user
  does not; the grace/suspended banner renders from status.

## Out of scope (Phase 2+)
Agency self-signup; in-app invoices/receipts UI (Stripe hosts them); usage-based metering; dunning
emails from VisionGuard (Stripe handles retries/emails); multi-currency; tax remittance workflow.
</content>
</invoke>
