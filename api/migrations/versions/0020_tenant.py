"""tenant schema: portal_submissions (agency-portal queue, Slice 12)

Revision ID: 0020_tenant
Revises: 0019_tenant
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0020_tenant"
down_revision: str | None = "0019_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    validate_schema_name(current_schema() or "")
    op.create_table(
        "portal_submissions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("need_type", sa.String(length=40), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("file_key", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="new"
        ),
        sa.Column("submitted_by_staff_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        schema=TENANT_SCHEMA_TOKEN,
    )
    op.create_index(
        "ix_portal_submissions_status",
        "portal_submissions",
        ["status"],
        schema=TENANT_SCHEMA_TOKEN,
    )
    # A per-user/day tip counter reads by submitter + created_at; index the submitter.
    op.create_index(
        "ix_portal_submissions_submitter",
        "portal_submissions",
        ["submitted_by_staff_id"],
        schema=TENANT_SCHEMA_TOKEN,
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    validate_schema_name(current_schema() or "")
    op.drop_table("portal_submissions", schema=TENANT_SCHEMA_TOKEN)
