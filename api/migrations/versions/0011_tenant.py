"""tenant schema: case lifecycle columns, case_events, case_notes

Revision ID: 0011_tenant
Revises: 0010_tenant
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0011_tenant"
down_revision: str | None = "0010_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASE_FK = f"{TENANT_SCHEMA_TOKEN}.cases.id"

# schema_translate_map doesn't rewrite the "tenant" token for ALTER TABLE / partial-index DDL,
# so these run as raw DDL against the validated real schema (sanctioned migration exception,
# CLAUDE.md #5 — same pattern as 0010).
_ADD_COLUMNS = (
    "ADD COLUMN source_url TEXT",
    "ADD COLUMN source_key VARCHAR(64)",
    "ADD COLUMN offender_key VARCHAR(300)",
    "ADD COLUMN assigned_staff_id INTEGER",
    "ADD COLUMN due_at TIMESTAMPTZ",
)
_DROP_COLUMNS = ("due_at", "assigned_staff_id", "offender_key", "source_key", "source_url")
_TERMINAL = ("dismissed", "withdrawn", "recovered", "closed")


def upgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")

    for clause in _ADD_COLUMNS:
        op.execute(f'ALTER TABLE "{schema}".cases {clause}')
    op.execute(f'CREATE INDEX ix_cases_offender_key ON "{schema}".cases (offender_key)')
    op.execute(f'CREATE INDEX ix_cases_status ON "{schema}".cases (status)')
    op.execute(f'CREATE INDEX ix_cases_due_at ON "{schema}".cases (due_at)')
    # No two OPEN cases for the same subject + canonical URL (terminal cases ignored → re-file).
    terminal = ", ".join(f"'{s}'" for s in _TERMINAL)
    op.execute(
        f'CREATE UNIQUE INDEX uq_open_case_source ON "{schema}".cases (subject_id, source_key) '
        f"WHERE status NOT IN ({terminal})"
    )

    op.create_table(
        "case_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("related_case_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_staff_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=50), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], [_CASE_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_case_id"], [_CASE_FK], ondelete="SET NULL"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_case_events_case", "case_events", ["case_id"], schema=TENANT_SCHEMA_TOKEN
    )

    op.create_table(
        "case_notes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("author_staff_id", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], [_CASE_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_case_notes_case", "case_notes", ["case_id"], schema=TENANT_SCHEMA_TOKEN
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    op.drop_table("case_notes", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("case_events", schema=TENANT_SCHEMA_TOKEN)
    op.execute(f'DROP INDEX IF EXISTS "{schema}".uq_open_case_source')
    op.execute(f'DROP INDEX IF EXISTS "{schema}".ix_cases_due_at')
    op.execute(f'DROP INDEX IF EXISTS "{schema}".ix_cases_status')
    op.execute(f'DROP INDEX IF EXISTS "{schema}".ix_cases_offender_key')
    for col in _DROP_COLUMNS:
        op.execute(f'ALTER TABLE "{schema}".cases DROP COLUMN IF EXISTS {col}')
