"""tenant schema: reports (append-only) + discovery_candidates.shown_at (Slice 10)

Revision ID: 0019_tenant
Revises: 0018_tenant
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0019_tenant"
down_revision: str | None = "0018_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _append_only(schema: str, table: str) -> None:
    """BEFORE UPDATE/DELETE trigger (fires for every role incl. the owner) + REVOKE — the same
    append-only guard used for notice_outcomes / notice_versions / custody_events. Raw SQL uses
    the validated real schema (schema_translate_map doesn't rewrite it)."""
    fn = f"{table}_no_mutate"
    op.execute(
        f'CREATE OR REPLACE FUNCTION "{schema}".{fn}() '
        "RETURNS trigger AS $$ BEGIN "
        f"RAISE EXCEPTION '{table} is append-only'; "
        "END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_update_delete "
        f'BEFORE UPDATE OR DELETE ON "{schema}".{table} '
        f'FOR EACH ROW EXECUTE FUNCTION "{schema}".{fn}()'
    )
    op.execute(f'REVOKE UPDATE, DELETE ON "{schema}".{table} FROM PUBLIC')


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    schema = validate_schema_name(current_schema() or "")
    # When a candidate was first shown to a reviewer (Slice 10, review-minutes metric).
    op.execute(
        f'ALTER TABLE "{schema}".discovery_candidates ADD COLUMN shown_at TIMESTAMPTZ'
    )
    # Sensitive-content flag on the case: default-deny for report imagery. NOT NULL DEFAULT TRUE
    # backfills every existing case as sensitive (Slice 10, CLAUDE.md #7).
    op.execute(
        f'ALTER TABLE "{schema}".cases ADD COLUMN sensitive BOOLEAN NOT NULL DEFAULT TRUE'
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "include_thumbnails", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("pdf_key", sa.Text(), nullable=False),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=False),
        sa.Column("json_key", sa.Text(), nullable=False),
        sa.Column("json_sha256", sa.String(length=64), nullable=False),
        sa.Column("generated_by_staff_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_reports_subject", "reports", ["subject_id"], schema=TENANT_SCHEMA_TOKEN
    )
    # Generated reports are an append-only ledger — never edited, only re-generated as new rows.
    _append_only(schema, "reports")


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    op.execute(f'DROP TRIGGER IF EXISTS reports_no_update_delete ON "{schema}".reports')
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".reports_no_mutate()')
    op.drop_table("reports", schema=TENANT_SCHEMA_TOKEN)
    op.execute(f'ALTER TABLE "{schema}".cases DROP COLUMN IF EXISTS sensitive')
    op.execute(
        f'ALTER TABLE "{schema}".discovery_candidates DROP COLUMN IF EXISTS shown_at'
    )
