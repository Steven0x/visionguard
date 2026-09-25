"""tenant schema: assets and subject_keywords

Revision ID: 0007_tenant
Revises: 0006_public
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope
from pgvector.sqlalchemy import Vector

revision: str = "0007_tenant"
down_revision: str | None = "0006_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_FK = f"{TENANT_SCHEMA_TOKEN}.subjects.id"
_ASSET_FK = f"{TENANT_SCHEMA_TOKEN}.assets.id"


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    op.create_table(
        "assets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("file_key", sa.String(length=500), nullable=False),
        sa.Column("thumbnail_key", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("phash", sa.String(length=16), nullable=True),
        sa.Column("embedding", Vector(512), nullable=True),
        sa.Column("duplicate_of_asset_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["duplicate_of_asset_id"], [_ASSET_FK], ondelete="SET NULL"
        ),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_assets_sha256", "assets", ["sha256"], schema=TENANT_SCHEMA_TOKEN
    )

    op.create_table(
        "subject_keywords",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        sa.UniqueConstraint("subject_id", "keyword", name="uq_subject_keyword"),
        schema=TENANT_SCHEMA_TOKEN,
    )

    # HNSW cosine index on the embedding. schema_translate_map does not rewrite raw SQL, so use
    # the validated real schema name here (migrations are the sanctioned place for this).
    schema = validate_schema_name(current_schema() or "")
    op.execute(
        f'CREATE INDEX ix_assets_embedding_hnsw ON "{schema}".assets '
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    op.drop_table("subject_keywords", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("assets", schema=TENANT_SCHEMA_TOKEN)
