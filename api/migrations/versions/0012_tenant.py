"""tenant schema: evidence_captures, evidence_artifacts, custody_events

Revision ID: 0012_tenant
Revises: 0011_tenant
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012_tenant"
down_revision: str | None = "0011_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASE_FK = f"{TENANT_SCHEMA_TOKEN}.cases.id"
_CAPTURE_FK = f"{TENANT_SCHEMA_TOKEN}.evidence_captures.id"


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    op.create_table(
        "evidence_captures",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requested_url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("page_title", sa.Text(), nullable=True),
        sa.Column("visible_counts", JSONB(), nullable=True),
        sa.Column("tool_version", sa.String(length=50), nullable=True),
        sa.Column("capture_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capture_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("timestamp_status", sa.String(length=20), nullable=True),
        sa.Column("tsa_url", sa.String(length=200), nullable=True),
        sa.Column("tsa_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], [_CASE_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_evidence_captures_case", "evidence_captures", ["case_id"], schema=TENANT_SCHEMA_TOKEN
    )

    op.create_table(
        "evidence_artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("capture_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["capture_id"], [_CAPTURE_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_evidence_artifacts_capture", "evidence_artifacts", ["capture_id"],
        schema=TENANT_SCHEMA_TOKEN,
    )

    op.create_table(
        "custody_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("capture_id", sa.BigInteger(), nullable=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("actor_staff_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["capture_id"], [_CAPTURE_FK], ondelete="SET NULL"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_custody_events_capture", "custody_events", ["capture_id"], schema=TENANT_SCHEMA_TOKEN
    )

    # Chain of custody is append-only (CLAUDE.md #6), same guarantee as audit_log: a BEFORE
    # UPDATE/DELETE trigger (fires for every role incl. the owner) + a REVOKE for defense in
    # depth. Raw SQL uses the validated real schema (translate-map doesn't rewrite it).
    schema = validate_schema_name(current_schema() or "")
    op.execute(
        f'CREATE OR REPLACE FUNCTION "{schema}".custody_events_no_mutate() '
        "RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'custody_events is append-only'; "
        "END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        'CREATE TRIGGER custody_events_no_update_delete '
        f'BEFORE UPDATE OR DELETE ON "{schema}".custody_events '
        f'FOR EACH ROW EXECUTE FUNCTION "{schema}".custody_events_no_mutate()'
    )
    op.execute(f'REVOKE UPDATE, DELETE ON "{schema}".custody_events FROM PUBLIC')


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    op.execute(
        f'DROP TRIGGER IF EXISTS custody_events_no_update_delete ON "{schema}".custody_events'
    )
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".custody_events_no_mutate()')
    op.drop_table("custody_events", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("evidence_artifacts", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("evidence_captures", schema=TENANT_SCHEMA_TOKEN)
