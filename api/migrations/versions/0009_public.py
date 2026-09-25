"""public schema: per-reviewer blur preference on staff

Revision ID: 0009_public
Revises: 0008_tenant
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.migration_scope import current_scope

revision: str = "0009_public"
down_revision: str | None = "0008_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "public":
        return
    op.add_column(
        "staff",
        sa.Column(
            "review_keep_blur",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    if current_scope() != "public":
        return
    op.drop_column("staff", "review_keep_blur")
