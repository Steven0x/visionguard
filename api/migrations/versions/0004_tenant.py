"""tenant schema: subjects and allowlist_entries

Revision ID: 0004_tenant
Revises: 0003_public
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN
from api.app.db.migration_scope import current_scope
from sqlalchemy.dialects import postgresql

revision: str = "0004_tenant"
down_revision: str | None = "0003_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    op.create_table(
        "subjects",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column(
            "stage_names",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "handles",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("residence_state", sa.String(length=2), nullable=True),
        sa.Column(
            "biometrics_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
        schema=TENANT_SCHEMA_TOKEN,
    )

    op.create_table(
        "allowlist_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=TENANT_SCHEMA_TOKEN,
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    op.drop_table("allowlist_entries", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("subjects", schema=TENANT_SCHEMA_TOKEN)
