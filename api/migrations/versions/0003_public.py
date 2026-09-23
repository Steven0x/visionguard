"""public schema: workspace contact fields

Revision ID: 0003_public
Revises: 0002_tenant
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.migration_scope import current_scope

revision: str = "0003_public"
down_revision: str | None = "0002_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "public":
        return
    op.add_column("workspaces", sa.Column("contact_name", sa.String(length=200), nullable=True))
    op.add_column("workspaces", sa.Column("contact_email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    if current_scope() != "public":
        return
    op.drop_column("workspaces", "contact_email")
    op.drop_column("workspaces", "contact_name")
