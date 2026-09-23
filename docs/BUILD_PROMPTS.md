# Build day: Claude Code playbook

Paste these into Claude Code one at a time, in order. Wait for each one to finish, pass its tests and pass review before moving on.

**Realistic target for today:** Slices 0–5 done and working (scaffold, workspaces, rights/consent, assets, discovery, review inbox). Slices 6–8 (cases, evidence, notices) if the day goes smoothly. Don't skip the review steps to go faster: that's how the dangerous bugs get in.

---

## Part A: One-time setup (≈45–60 min, do this first)

### 1. Install tools on your Mac

```bash
# Check what you have
node -v        # need 18+
python3 -V     # need 3.12+ (brew install python@3.12 if not)
git --version

# Claude Code (see docs.claude.com for the current install command if this changes)
npm install -g @anthropic-ai/claude-code
```

### 2. Create accounts and collect keys

Put every key in `~/Developer/visionguard/.env` (Claude Code creates `.env.example` in Slice 0; copy it to `.env` and fill it in). **Never paste keys into chat.**

| Service | What to create | Keys you'll need | Needed by |
| --- | --- | --- | --- |
| GitHub | Private repo `visionguard` | — | Slice 0 |
| Supabase | New project (region: US East). In SQL editor run `create extension if not exists vector;` | `DATABASE_URL` (Session pooler connection string), project URL, service role key | Slice 0 |
| Clerk | New application (email sign-in only). Turn off public sign-ups; you'll invite staff | `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` | Slice 0 |
| Cloudflare R2 | Buckets `vg-assets` and `vg-evidence`; on `vg-evidence`, add a **bucket lock** rule (retention, e.g. 7 years). API token with read/write on both | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Slice 3 (assets), 7 (evidence) |
| Upstash | Redis database (same region) | `REDIS_URL` (the `rediss://` one) | Slice 3 |
| SerpApi | Account (free tier is fine for testing) | `SERPAPI_KEY` | Slice 4 |
| TinEye | Optional today | `TINEYE_API_KEY` | Slice 4 (optional) |
| SendGrid | Can wait | `SENDGRID_API_KEY` | Slice 8 |
| Vercel | Can wait until deploy | — | After Slice 5 |

### 3. Start the repo

```bash
cd ~/Developer/visionguard
rm -rf agents-to-move           # empty leftover folder
git init && git add . && git commit -m "docs: product outline, backlog, agents, ops kit"
git branch -M main
git remote add origin git@github.com:<you>/visionguard.git && git push -u origin main
claude
```

Inside Claude Code, run `/agents` and confirm you see **reviewer**, **red-team** and **claims-checker**.

The product outline is already in the repo at `docs/product-outline.md`.

---

## Part B: The slices

Use **plan mode** (Shift+Tab) for the first message of each slice. Read the plan and approve it, then let it build.

### Prompt 0: Scaffold and foundations

```
Read CLAUDE.md and docs/BACKLOG.md. We're building Slice 0 today.

Plan the monorepo scaffold: api/ (FastAPI, SQLAlchemy 2, Alembic, Pydantic v2), worker/ (Celery + Redis), web/ (React + TypeScript + Vite + Tailwind + Clerk), docs/, templates/.
Requirements:
- Clerk auth for staff only; roles admin/reviewer checked on every API route.
- Schema-per-tenant Postgres on Supabase with a tenant router; a public schema for workspaces/staff; Alembic migrations that run across all tenant schemas.
- Audit log table + helper.
- Makefile with dev, test, lint, migrate. .env.example with every variable. ruff, mypy, eslint, tsc, pytest, vitest.
- GitHub Actions CI running lint + tests.
- A test proving workspace A cannot read workspace B's data.
Keep it minimal: no features beyond Slice 0. Show me the plan before writing code.
```

After it's built and `make test` passes:

```
Run the reviewer agent and the red-team agent on everything built so far. Fix blockers and should-fixes, then re-run make test. Commit with a conventional message.
```

### Prompt 1: Workspaces and subjects

```
Build Slice 1 from docs/BACKLOG.md (workspaces and subjects), UI to API to DB. Include CSV import of subjects and the biometrics_blocked rule for IL/WA residents. Write the spec to docs/specs/workspaces-subjects.md first, then implement against it. Tenant-isolation tests for every new table.
```

Then: `Run reviewer and red-team on this slice, fix findings, make test, commit.`

### Prompt 2: Rights and consent

```
Build Slice 2 (rights, consent and agent-authorization records). Spec first in docs/specs/rights-consent.md. Documents upload to R2 (vg-assets) under a tenant-scoped key. Show on each subject which claim types are currently supported, derived from docs/legal/claims-matrix.md. Build the consent-revocation hook that hard-deletes biometric data (it will have nothing to delete yet; test the hook anyway).
```

Then: `Run reviewer, red-team and claims-checker on this slice, fix findings, make test, commit.`

### Prompt 3: Assets and fingerprints

```
Build Slice 3 (assets and fingerprints). Spec first. Upload images (and video, extracting frames) to R2; a Celery task computes pHash and an OpenCLIP embedding stored in pgvector. Detect duplicate uploads by hash. Add text identifiers per subject. Validate uploads (type sniffing, size limits, no SVG/HTML execution).
```

Then: `Run reviewer and red-team on this slice (focus on uploads), fix findings, make test, commit.`

### Prompt 4: Discovery v1

```
Build Slice 4 (discovery v1). Spec first. Three sources: (1) manual URL intake, single or bulk; (2) scheduled reverse image jobs per asset via SerpApi Google Lens (TinEye optional behind a flag); (3) keyword search jobs. The URL fetcher must be SSRF-safe (block private and loopback ranges, metadata endpoints, non-http schemes; re-check after redirects). Per-workspace scan budget and frequency; log provider cost per call. Results become candidate matches.
```

Then: `Run reviewer and red-team on this slice (SSRF focus), fix findings, make test, commit.`

### Prompt 5: Matching and review inbox

```
Build Slice 5 (matching and review inbox). Spec first. Scoring: pHash distance, then embedding similarity, then rules (source type, risky keywords, allowlist). Inbox UI: original vs found side by side, score, source, suggested claim type, keyboard shortcuts (J/K to move, C confirm, D dismiss with reason), bulk actions by domain or account. Confirm creates a case stub; dismiss stores a reason. Every decision is saved as a labeled example. The allowlist is checked before a candidate reaches the inbox.
```

Then: `Run reviewer on this slice, fix findings, make test, commit.`

**Checkpoint:** run `make dev`, sign in, create a workspace, add one subject, upload 5 photos, paste 3 URLs, and review them in the inbox. If that flow works end to end, today is a success.

### Prompt 6: Cases and lifecycle (if time)

```
Build Slice 6. Spec first. A case service with an enforced state machine exactly as in CLAUDE.md; every transition audited; illegal transitions rejected (tests). Case view with a timeline. Group cases by offender.
```

Then: `Run reviewer and claims-checker, fix findings, make test, commit.`

### Prompt 7: Evidence capture (if time)

```
Build Slice 7. Reuse the logic in ops/capture/capture.py (Playwright screenshot, HTML, MHTML, SHA-256 manifest, RFC 3161 timestamp) as a Celery task triggered on case confirm. Store artifacts in R2 vg-evidence (bucket lock). Chain-of-custody log for every access. Evidence pack PDF export and a standalone verify command.
```

Then: `Run reviewer and red-team, fix findings, make test, commit.`

### Prompt 8: Notices (if time)

```
Build Slice 8. Spec first. Claim selection is limited to what the subject's rights records support per docs/legal/claims-matrix.md. A channel registry (platform, claim types, method, required fields). Notice templates per claim and channel, all marked unapproved; unapproved templates cannot be sent. Approval records approved_by. Email channels via SendGrid; web-form channels produce a copy-ready packet for staff. A trademark case can never route to DMCA (test).
```

Then: `Run reviewer, claims-checker and red-team, fix findings, make test, commit.`

---

## Working tips

- **If a slice goes sideways:** `Stop. Summarize what's broken, what you tried, and propose two options.` Then pick one.
- **If context gets long:** start a fresh session with `/clear` between slices. `CLAUDE.md` and the specs carry the context.
- **Parallel work (optional, after Slice 1):** open a second terminal, create a git worktree for the frontend polish of a finished slice while the main session builds the next backend slice. Only for truly independent work.
- **Don't approve** anything that weakens a Non-negotiable in `CLAUDE.md` to get a test passing.
