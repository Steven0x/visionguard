"""tenant schema: csam_incidents (admin escalation queue; no image bytes)

Revision ID: 0013_tenant
Revises: 0012_tenant
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN
from api.app.db.migration_scope import current_scope

revision: str = "0013_tenant"
down_revision: str | None = "0012_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "tenant":
        return
    op.create_table(
        "csam_incidents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("case_id", sa.BigInteger(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_csam_incidents_status", "csam_incidents", ["status"], schema=TENANT_SCHEMA_TOKEN
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    op.drop_table("csam_incidents", schema=TENANT_SCHEMA_TOKEN)
