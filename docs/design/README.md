# Slice 14 — UI polish (design system)

A Tailwind design system ("Clarity" direction) applied across the staff console and the agency
portal. **No backend behavior changed** — only `web/`, the Tailwind config, and a dev-only,
env-gated screenshot path.

## Direction

**Clarity** (chosen over "Focus"): indigo primary, slate neutrals, Inter with a native
system-sans fallback (no webfont is fetched), 8px radius, soft shadows, generous spacing; full
light + dark theme. Tokens live in `web/src/index.css`
(`:root` / `.dark` CSS variables) and `web/tailwind.config.js`. The two candidate directions are
preserved as `mockups/direction-{a,b}.{html,png}`.

## What changed

- **Shells.** Staff gets a sidebar + workspace switcher + section nav (`AppShell`); the portal
  gets a branded header with the VisionGuard wordmark + agency name (`PortalShell`).
- **Primitives.** `web/src/components/ui/*`: Button, Input, Textarea, Select, Card, Table, Badge,
  StatusBadge, Tabs, Modal, Toast, EmptyState, Skeleton (hand-rolled Tailwind, no new deps).
- **States.** Every screen has a loading skeleton, an empty state with a next action, and readable
  errors (`web/src/errors.ts`) — no more `Loading…` or raw `String(e)`.
- **Status badges.** One color per case status (`ui/StatusBadge` `STATUS_TONE`), used in the staff
  inbox, cases, case view, reports, and the portal.
- **Dialogs.** `window.prompt`/`window.confirm` replaced by `Modal` (reopen candidate, transition
  note, evidence-pack export).
- **Accessibility.** Labels on inputs, visible focus rings, keyboard-navigable Tabs/Modal, dark/
  light AA. Responsive: staff to tablet, portal to phone. The review inbox keeps J/K/C/D + a hint
  bar; nothing was added to the hot path.
- **Sensitive content unchanged.** No new component renders an image; sensitive/`ncii` cases show
  no thumbnail. Guarded by `portal/portal_no_images.test.tsx` and `EvidenceSection.test.tsx`.

## Before / after

Screens captured with the demo data (`make seed-demo`). `before/` is pre-slice; `after/` is the
redesign. The staff workspace page, previously one long stack (`before/staff-workspace-detail*`),
is now split into sidebar sections (`after/staff-{review-inbox,cases,followups,reports,subjects,
settings}`).

| Screen | Before | After |
| --- | --- | --- |
| Staff · workspace list | `before/staff-workspace-list.png` | `after/staff-workspace-list.png` |
| Staff · review inbox | `before/staff-review-inbox.png` | `after/staff-review-inbox.png` (+ `-dark`, `-tablet`) |
| Staff · cases | `before/staff-cases.png` | `after/staff-cases.png` |
| Staff · case detail | `before/staff-case-detail.png` | `after/staff-case-detail.png` |
| Staff · evidence | `before/staff-evidence-section.png` | `after/staff-evidence-section.png` |
| Staff · follow-ups | (in `before/staff-workspace-detail.png`) | `after/staff-followups.png` |
| Staff · reports | (in `before/staff-workspace-detail.png`) | `after/staff-reports.png` |
| Staff · subjects | (in `before/staff-workspace-detail.png`) | `after/staff-subjects.png` |
| Staff · subject detail | `before/staff-subject-detail.png` | `after/staff-subject-detail.png` |
| Staff · settings | (in `before/staff-workspace-detail.png`) | `after/staff-settings.png` |
| Portal · cases | `before/portal-cases.png` | `after/portal-cases.png` (+ `-dark`) |
| Portal · subjects | `before/portal-subjects.png` | `after/portal-subjects.png` |
| Portal · needs | `before/portal-needs.png` | `after/portal-needs.png` |
| Portal · reports | `before/portal-reports.png` | `after/portal-reports.png` |
| Portal · billing | `before/portal-billing.png` | `after/portal-billing.png` |
| Portal · case detail | `before/portal-case-detail.png` | `after/portal-case-detail.png` |
| Portal · mobile | `before/portal-mobile-cases.png` | `after/portal-mobile-cases.png` |

## Regenerating screenshots (dev only)

> **Run only against a local dev database.** `scripts/design_capture.py` writes a persistent
> `Staff(role=agency, clerk_user_id="dev_capture_agency")` row (+ one workspace grant) to whatever
> `DATABASE_URL` names. It is idempotent and the identity is unusable on any deployment (its HS256
> token is only accepted when `AUTH_TEST_MODE` is on, which the config guard forbids in
> staging/production), but don't point it at a shared/staging DB.

Screenshots come from Playwright reusing the existing `AUTH_TEST_MODE` Clerk bypass — no new
backend auth code. A `VITE_DEV_AUTH=1` branch in `App.tsx`/`useToken.ts` reads a pre-minted test
token from `localStorage`; it is dead in every real build.

```bash
make seed-demo
# capture API (test-mode) + capture web (dev-auth), on their own ports:
AUTH_TEST_MODE=1 ALLOWED_ORIGINS=http://localhost:5174 \
  .venv/bin/uvicorn api.app.main:app --port 8001 &
npm --prefix web run dev -- --mode capture --port 5174 &   # reads web/.env.capture
.venv/bin/python scripts/design_capture.py docs/design/after http://localhost:5174
```
