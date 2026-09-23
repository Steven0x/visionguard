"""public schema: workspaces, staff, staff_workspace_access

Revision ID: 0001_public
Revises:
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.migration_scope import current_scope

revision: str = "0001_public"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "public":
        return

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("plan", sa.String(length=50), nullable=False, server_default="starter"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )

    op.create_table(
        "staff",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "all_workspaces", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("clerk_user_id", name="uq_staff_clerk_user_id"),
    )

    op.create_table(
        "staff_workspace_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"], ["staff.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("staff_id", "workspace_id", name="uq_staff_workspace"),
    )


def downgrade() -> None:
    if current_scope() != "public":
        return
    op.drop_table("staff_workspace_access")
    op.drop_table("staff")
    op.drop_table("workspaces")
