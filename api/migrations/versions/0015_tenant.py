"""tenant schema: notices, notice_versions (append-only), filing_log

Revision ID: 0015_tenant
Revises: 0014_public
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0015_tenant"
down_revision: str | None = "0014_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASE_FK = f"{TENANT_SCHEMA_TOKEN}.cases.id"
_NOTICE_FK = f"{TENANT_SCHEMA_TOKEN}.notices.id"


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    op.create_table(
        "notices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("claim_type", sa.String(length=30), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sealed_capture_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("approved_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_version", sa.Integer(), nullable=True),
        sa.Column(
            "fair_use_considered", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("sent_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], [_CASE_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index("ix_notices_case", "notices", ["case_id"], schema=TENANT_SCHEMA_TOKEN)

    op.create_table(
        "notice_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("notice_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("edited_by_staff_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["notice_id"], [_NOTICE_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_notice_versions_notice", "notice_versions", ["notice_id"], schema=TENANT_SCHEMA_TOKEN
    )

    op.create_table(
        "filing_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("notice_id", sa.BigInteger(), nullable=True),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("claim_type", sa.String(length=30), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("ticket_number", sa.String(length=200), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("filed_by_staff_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], [_CASE_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notice_id"], [_NOTICE_FK], ondelete="SET NULL"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index("ix_filing_log_case", "filing_log", ["case_id"], schema=TENANT_SCHEMA_TOKEN)

    # notice_versions is the append-only draft history (like case_notes / custody_events): a
    # BEFORE UPDATE/DELETE trigger (fires for every role incl. the owner) + a REVOKE for defense
    # in depth. Raw SQL uses the validated real schema (translate-map doesn't rewrite it).
    schema = validate_schema_name(current_schema() or "")
    op.execute(
        f'CREATE OR REPLACE FUNCTION "{schema}".notice_versions_no_mutate() '
        "RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'notice_versions is append-only'; "
        "END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        'CREATE TRIGGER notice_versions_no_update_delete '
        f'BEFORE UPDATE OR DELETE ON "{schema}".notice_versions '
        f'FOR EACH ROW EXECUTE FUNCTION "{schema}".notice_versions_no_mutate()'
    )
    op.execute(f'REVOKE UPDATE, DELETE ON "{schema}".notice_versions FROM PUBLIC')


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    op.execute(
        f'DROP TRIGGER IF EXISTS notice_versions_no_update_delete ON '
        f'"{schema}".notice_versions'
    )
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".notice_versions_no_mutate()')
    op.drop_table("filing_log", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("notice_versions", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("notices", schema=TENANT_SCHEMA_TOKEN)
