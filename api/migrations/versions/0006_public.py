"""public schema: enable the pgvector extension

Revision ID: 0006_public
Revises: 0005_tenant
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from api.app.db.migration_scope import current_scope

revision: str = "0006_public"
down_revision: str | None = "0005_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "public":
        return
    # Global type; created once so tenant tables can use vector(512).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    if current_scope() != "public":
        return
    # Leave the extension in place; dropping it would break every tenant assets table.
