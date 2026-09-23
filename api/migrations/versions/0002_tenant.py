"""tenant schema: append-only audit_log

Revision ID: 0002_tenant
Revises: 0001_public
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope
from sqlalchemy.dialects import postgresql

revision: str = "0002_tenant"
down_revision: str | None = "0001_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("actor_staff_id", sa.Integer(), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=TENANT_SCHEMA_TOKEN,  # rewritten to the real schema by schema_translate_map
    )

    # Append-only. schema_translate_map does NOT rewrite raw SQL, so use the real (already
    # validated) schema name here.
    schema = validate_schema_name(current_schema() or "")
    # 1) A BEFORE UPDATE/DELETE trigger enforces immutability for EVERY role, including the
    #    table owner (triggers fire regardless of privileges). This is the real guarantee
    #    today, while the app still connects as the owner (see docs/BACKLOG.md follow-up).
    op.execute(
        f'CREATE OR REPLACE FUNCTION "{schema}".audit_log_no_mutate() '
        "RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'audit_log is append-only'; "
        "END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        f'CREATE TRIGGER audit_log_no_update_delete '
        f'BEFORE UPDATE OR DELETE ON "{schema}".audit_log '
        f'FOR EACH ROW EXECUTE FUNCTION "{schema}".audit_log_no_mutate()'
    )
    # 2) Defense in depth: revoke from PUBLIC so a future non-owner app role (vg_app) also
    #    lacks UPDATE/DELETE at the privilege layer.
    op.execute(f'REVOKE UPDATE, DELETE ON "{schema}".audit_log FROM PUBLIC')


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    op.execute(f'DROP TRIGGER IF EXISTS audit_log_no_update_delete ON "{schema}".audit_log')
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".audit_log_no_mutate()')
    op.drop_table("audit_log", schema=TENANT_SCHEMA_TOKEN)
