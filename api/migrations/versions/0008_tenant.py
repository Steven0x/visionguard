"""tenant schema: discovery settings, runs, candidates

Revision ID: 0008_tenant
Revises: 0007_tenant
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope
from pgvector.sqlalchemy import Vector

revision: str = "0008_tenant"
down_revision: str | None = "0007_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_FK = f"{TENANT_SCHEMA_TOKEN}.subjects.id"
_ASSET_FK = f"{TENANT_SCHEMA_TOKEN}.assets.id"
_RUN_FK = f"{TENANT_SCHEMA_TOKEN}.discovery_runs.id"


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    op.create_table(
        "discovery_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("monthly_call_budget", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("scan_frequency", sa.String(length=20), nullable=False, server_default="off"),
        sa.Column("tineye_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "thumbnail_retention_days", sa.Integer(), nullable=False, server_default="90"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=TENANT_SCHEMA_TOKEN,
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("calls_made", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], [_ASSET_FK], ondelete="SET NULL"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_discovery_runs_started_at", "discovery_runs", ["started_at"],
        schema=TENANT_SCHEMA_TOKEN,
    )

    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("phash", sa.String(length=16), nullable=True),
        sa.Column("embedding", Vector(512), nullable=True),
        sa.Column("thumbnail_key", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], [_RUN_FK], ondelete="SET NULL"),
        sa.UniqueConstraint("subject_id", "source_key", name="uq_candidate_source"),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_discovery_candidates_sha256", "discovery_candidates", ["sha256"],
        schema=TENANT_SCHEMA_TOKEN,
    )

    schema = validate_schema_name(current_schema() or "")
    op.execute(
        f'CREATE INDEX ix_discovery_candidates_embedding_hnsw ON "{schema}".discovery_candidates '
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    op.drop_table("discovery_candidates", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("discovery_runs", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("discovery_settings", schema=TENANT_SCHEMA_TOKEN)
