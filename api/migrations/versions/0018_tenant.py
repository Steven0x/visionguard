"""tenant schema: notice_outcomes + url_rechecks (append-only), case proposal columns

Revision ID: 0018_tenant
Revises: 0017_public
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0018_tenant"
down_revision: str | None = "0017_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASE_FK = f"{TENANT_SCHEMA_TOKEN}.cases.id"
_NOTICE_FK = f"{TENANT_SCHEMA_TOKEN}.notices.id"
_OUTCOME_FK = f"{TENANT_SCHEMA_TOKEN}.notice_outcomes.id"


def _append_only(schema: str, table: str) -> None:
    """A BEFORE UPDATE/DELETE trigger (fires for every role incl. the owner) + REVOKE — the same
    append-only guard used for notice_versions / custody_events. Raw SQL uses the validated real
    schema (schema_translate_map doesn't rewrite it)."""
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

    # Proposal flags on the case: set by the re-check beat, cleared on human confirm/dismiss.
    schema = validate_schema_name(current_schema() or "")
    op.execute(
        f'ALTER TABLE "{schema}".cases ADD COLUMN removal_proposed_at TIMESTAMPTZ'
    )
    op.execute(
        f'ALTER TABLE "{schema}".cases ADD COLUMN reappearance_proposed_at TIMESTAMPTZ'
    )
    # When a removal proposal was last dismissed — suppresses re-proposal until a fresh gone
    # streak accrues entirely after it, so a dismissed false positive isn't re-raised next beat.
    op.execute(
        f'ALTER TABLE "{schema}".cases ADD COLUMN removal_dismissed_at TIMESTAMPTZ'
    )
    # A removed case whose monitoring rechecks are ALL `live` (never observed gone) — the removal is
    # unverified (a soft-404 platform serves 200 for removed content). Held back from auto-close for
    # a human to confirm (close) or reopen.
    op.execute(
        f'ALTER TABLE "{schema}".cases ADD COLUMN removal_unverified_at TIMESTAMPTZ'
    )

    op.create_table(
        "notice_outcomes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("notice_id", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("effective_at", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("supersedes_id", sa.BigInteger(), nullable=True),
        sa.Column("recorded_by_staff_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], [_CASE_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notice_id"], [_NOTICE_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], [_OUTCOME_FK], ondelete="SET NULL"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_notice_outcomes_case", "notice_outcomes", ["case_id"], schema=TENANT_SCHEMA_TOKEN
    )
    op.create_index(
        "ix_notice_outcomes_notice", "notice_outcomes", ["notice_id"], schema=TENANT_SCHEMA_TOKEN
    )

    op.create_table(
        "url_rechecks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("probed_url", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(length=10), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], [_CASE_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_url_rechecks_case", "url_rechecks", ["case_id"], schema=TENANT_SCHEMA_TOKEN
    )

    # Both tables are append-only platform-response / probe history.
    _append_only(schema, "notice_outcomes")
    _append_only(schema, "url_rechecks")


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    for table in ("url_rechecks", "notice_outcomes"):
        op.execute(
            f'DROP TRIGGER IF EXISTS {table}_no_update_delete ON "{schema}".{table}'
        )
        op.execute(f'DROP FUNCTION IF EXISTS "{schema}".{table}_no_mutate()')
    op.drop_table("url_rechecks", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("notice_outcomes", schema=TENANT_SCHEMA_TOKEN)
    op.execute(f'ALTER TABLE "{schema}".cases DROP COLUMN IF EXISTS removal_unverified_at')
    op.execute(f'ALTER TABLE "{schema}".cases DROP COLUMN IF EXISTS removal_dismissed_at')
    op.execute(f'ALTER TABLE "{schema}".cases DROP COLUMN IF EXISTS reappearance_proposed_at')
    op.execute(f'ALTER TABLE "{schema}".cases DROP COLUMN IF EXISTS removal_proposed_at')
