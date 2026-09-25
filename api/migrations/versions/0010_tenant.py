"""tenant schema: candidate review/matching columns, cases, review_decisions

Revision ID: 0010_tenant
Revises: 0009_public
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0010_tenant"
down_revision: str | None = "0009_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_FK = f"{TENANT_SCHEMA_TOKEN}.subjects.id"
_ASSET_FK = f"{TENANT_SCHEMA_TOKEN}.assets.id"
_CANDIDATE_FK = f"{TENANT_SCHEMA_TOKEN}.discovery_candidates.id"

# Columns added to the existing discovery_candidates table. schema_translate_map does not
# rewrite the "tenant" token for ALTER TABLE / ADD CONSTRAINT the way it does for CREATE TABLE,
# so these run as raw DDL against the validated real schema — the sanctioned migration exception
# (CLAUDE.md #5), same pattern as the HNSW index in 0008.
_ADD_COLUMNS = (
    "ADD COLUMN title TEXT",
    "ADD COLUMN review_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
    "ADD COLUMN score INTEGER",
    "ADD COLUMN score_breakdown JSONB",
    "ADD COLUMN best_match_asset_id BIGINT",
    "ADD COLUMN matched_at TIMESTAMPTZ",
    "ADD COLUMN dismiss_reason VARCHAR(30)",
)
_DROP_COLUMNS = (
    "dismiss_reason",
    "matched_at",
    "best_match_asset_id",
    "score_breakdown",
    "score",
    "review_status",
    "title",
)


def upgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")

    # ── Extend discovery_candidates with review/matching state ──
    for clause in _ADD_COLUMNS:
        op.execute(f'ALTER TABLE "{schema}".discovery_candidates {clause}')
    op.execute(
        f'ALTER TABLE "{schema}".discovery_candidates '
        "ADD CONSTRAINT fk_candidate_best_asset "
        f'FOREIGN KEY (best_match_asset_id) REFERENCES "{schema}".assets(id) '
        "ON DELETE SET NULL"
    )
    op.execute(
        f'CREATE INDEX ix_discovery_candidates_review_status '
        f'ON "{schema}".discovery_candidates (review_status)'
    )

    # ── cases (stub — full lifecycle in Slice 6) ──
    op.create_table(
        "cases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("matched_asset_id", sa.BigInteger(), nullable=True),
        sa.Column("claim_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="confirmed"),
        sa.Column("opened_by_staff_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], [_CANDIDATE_FK], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matched_asset_id"], [_ASSET_FK], ondelete="SET NULL"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_cases_matched_asset", "cases", ["matched_asset_id"], schema=TENANT_SCHEMA_TOKEN
    )
    op.create_index(
        "ix_cases_candidate", "cases", ["candidate_id"], schema=TENANT_SCHEMA_TOKEN
    )

    # ── review_decisions (labeled training examples) ──
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=True),
        sa.Column("claim_type", sa.String(length=30), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by_staff_id", sa.Integer(), nullable=True),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["candidate_id"], [_CANDIDATE_FK], ondelete="SET NULL"),
        schema=TENANT_SCHEMA_TOKEN,
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    op.drop_table("review_decisions", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("cases", schema=TENANT_SCHEMA_TOKEN)
    op.execute(f'DROP INDEX IF EXISTS "{schema}".ix_discovery_candidates_review_status')
    op.execute(
        f'ALTER TABLE "{schema}".discovery_candidates '
        "DROP CONSTRAINT IF EXISTS fk_candidate_best_asset"
    )
    for col in _DROP_COLUMNS:
        op.execute(f'ALTER TABLE "{schema}".discovery_candidates DROP COLUMN IF EXISTS {col}')
