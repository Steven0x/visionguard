# ADR 0016: Billing on Stripe (Slice 13)

Status: accepted (2026-10-01)

## Context

Phase 1 needs to charge 5–10 agencies per active subject, with onboarding audits and design-partner
discounts, without VisionGuard ever handling card data or writing money math it could get wrong. The
overriding risks are financial correctness (never under/over-charge), security (an unauthenticated
webhook; no tampering with plan state or quantity), and the product rule that **billing must never
stop work already filed** and must **never delete data** (CLAUDE.md spirit; see
`docs/specs/billing.md`).

## Decisions

### 1. Stripe hosted, with a backend abstraction
Checkout (subscribe + the one-time audit) and the Customer Portal (card/ACH/invoices/cancel) are
Stripe-hosted; we store IDs and a thin mirror only. A `StripeClient` protocol with `stripe` and
`fake` backends mirrors the existing `fetcher`/`provider`/`capture`/`csam` pattern, so tests never
touch the network and the config guard can forbid `fake` outside dev/test and force `stripe` in
deployments.

### 2. No money math in our code — pricing lives on Stripe Price objects
Unit prices, the **volume** 15%-off-at-20 tier, and the 2-months-free annual prices are Stripe Price
objects referenced by env price IDs. Our code only sets a subscription **quantity** and attaches
**coupons/credits**. Volume (not graduated) tiering is chosen because "15% off when you reach 20"
means the whole quantity is discounted — which volume tiering expresses directly. Rationale:
correctness and auditability live where the invoices are generated; a price change is an env change,
not a code deploy.

### 3. Quantity is server-derived and idempotent; drift is corrected, never trusted
Quantity is always `max(active_subject_count, BILLING_MIN_QUANTITY=5)`, set absolutely (not a
delta) from a Celery task that recomputes from the live count. **No endpoint accepts a quantity**, so
it cannot be manipulated to underpay. Any observed quantity that differs from the derived value
(webhook, re-fetch, daily reconciliation) is reset and audited `quantity_corrected`. Rationale:
absolute+recompute makes lost/duplicated/out-of-order events harmless.

### 4. Stripe is the source of truth; webhooks re-fetch rather than trust payloads
The webhook is unauthenticated but **signature-gated**, **idempotent on event id** (a
`billing_events` ledger), and on any subscription/invoice event **re-fetches the subscription from
Stripe** to recompute the mirror — so out-of-order or stale events cannot regress state. The
workspace is resolved from our stored `stripe_customer_id`; an unknown customer is recorded and
ignored, never auto-mapped. `past_due_since` is stamped the first time `past_due` is seen and never
reset by replays/re-fetches, so the grace window can't be reset by a resent event. The route is
explicitly added to the default-deny route-walk allowlist.

### 5. Customer created server-side, one per workspace, never re-mapped
We create the Stripe customer before Checkout and store a **unique** `stripe_customer_id`. Webhook
data never re-points an existing customer at a different workspace. Rationale: the customer↔workspace
mapping is the trust root for the unauthenticated webhook; it must be set only by us.

### 6. Mirror and ledger live in the public schema
`workspace_billing` and `billing_events` hold only Stripe IDs and per-workspace plan config — the
same altitude as the `workspaces` row, no subject/case/evidence data — so they are public and the
per-tenant isolation-test rule (CLAUDE.md #5) does not apply. Billing **audit** rows still land in
the tenant `audit_log` via a tenant session. `workspaces.plan` stays a free-text ops label; the
billing tier is `plan_tier`, kept separate to avoid coupling an ops label to Stripe state.

### 7. `billing_mode` = stripe | manual
`manual` (design partners, demos, legacy) is invoiced outside Stripe and **exempt from all gates**;
existing workspaces migrate to `manual` on rollout so nothing breaks. Only admins switch mode
(audited). Gates apply only in `stripe` mode.

### 8. Suspension pauses only new work; it never touches filed work or data
Suspended = `past_due` past grace, `canceled`, or `stripe`-mode `none` (never subscribed). It gates
exactly two things — **new subjects** and **new discovery jobs** — and nothing else. Recording
outcomes, re-checks on filed cases, withdrawals, evidence access, and report generation/download are
never gated, and nothing is ever deleted for non-payment. Enforced at the service choke points
(`enforce_can_add_subject`, `dispatch_scheduled_scans`, `intake_urls`) with a test per protected
path.

### 9. Customer Portal disallows quantity and plan edits by configuration
The Billing-Portal configuration (set via API, referenced by `STRIPE_PORTAL_CONFIGURATION_ID`)
disables subscription quantity changes and plan switching, leaving customers card/ACH/invoice
management and cancellation. Quantity is ours to derive; plan changes go through staff. This is
enforced by configuration, not left to a dashboard default.

### 10. `automatic_tax` off by default
`STRIPE_AUTOMATIC_TAX` defaults off and is passed to Checkout; it is enabled only after confirming
sales-tax nexus/registration, so we don't collect tax we aren't registered to remit.

## Consequences

- A deployment cannot boot without real Stripe keys (live in production, test in staging), matching
  the SendGrid/CSAM guard posture.
- The app is resilient to missed/duplicate/out-of-order webhooks via re-fetch + idempotency + daily
  reconciliation, at the cost of extra Stripe reads.
- Agencies cannot change quantity or plan themselves; staff drive plan, the system drives quantity —
  consistent with the concierge model.
- Dependency: the `stripe` Python SDK (behind the `stripe` backend / `[billing]` extra). Recorded
  here per CLAUDE.md "ask before adding a dependency"; the `fake` backend keeps tests SDK-free.
</content>
