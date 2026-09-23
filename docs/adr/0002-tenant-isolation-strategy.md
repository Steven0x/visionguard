# ADR 0002: Tenant isolation strategy

- **Status:** Accepted
- **Date:** 2026-09-23
- **Context:** CLAUDE.md non-negotiable #5 requires schema-per-tenant Postgres, no
  cross-tenant joins, and an isolation test for every tenant table. Slice 0 must set the
  mechanism every later slice relies on.

## Decision

**Schema-per-tenant with SQLAlchemy `schema_translate_map`.**

- Shared tables (`workspaces`, `staff`, `staff_workspace_access`) live in `public`.
- Tenant tables (starting with `audit_log`) are declared on `TenantBase` with the symbolic
  schema token `"tenant"`. Per request, the connection is bound with
  `execution_options(schema_translate_map={"tenant": "ws_<id>"})`, so ORM statements resolve
  tenant tables to exactly one workspace schema and no other.
- Chosen over `SET search_path` because translate-map binding is explicit per connection and
  not vulnerable to search_path leaking across pooled connections (Supabase session pooler).

**Schema names are derived, never client-supplied.**

- The name is computed from a trusted workspace id (`ws_<id>`) and validated against
  `^ws_[a-z0-9_]+$` (`validate_schema_name`) before any `CREATE SCHEMA` or translate-map
  bind. A hostile id cannot inject SQL or reach another schema. Tested in
  `api/tests/test_schema_safety.py`.

**Migrations run across all schemas.**

- One linear history; `migrations/env.py` runs a public pass, then loops every provisioned
  workspace schema, each with its own `alembic_version` (via `version_table_schema`).
  Migrations guard on the current scope so they touch only their own tables.

**`audit_log` is append-only.**

- No update/delete path exists in code. The tenant migration additionally
  `REVOKE UPDATE, DELETE ON <schema>.audit_log FROM PUBLIC`. In production the app connects
  as a **non-owner** role so the revoke is effective (an owner retains implicit privileges).

## Limitation (must-follow rule)

`schema_translate_map` rewrites **ORM/Core** statements only — it does **not** rewrite raw
`text()` SQL. Raw SQL that names a schema would bypass isolation.

**Rule:** tenant data is reached only through ORM tenant sessions; no raw SQL may name a
schema. The only sanctioned exceptions are provisioning DDL (`CREATE SCHEMA`) and the audit
`REVOKE`, which use a name already validated by `validate_schema_name`. This is recorded as
a non-negotiable in CLAUDE.md.

## Consequences

- Every new tenant table gets an isolation test (as `audit_log` does in `test_isolation.py`).
- Cross-tenant reporting, if ever needed, must aggregate per-schema in app code — never a
  cross-schema SQL join.
