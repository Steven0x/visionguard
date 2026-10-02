"""tenant schema: discovery candidate source/suggested_claim + settings second_reverse_engine

Revision ID: 0022_tenant
Revises: 0021_public
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0022_tenant"
down_revision: str | None = "0021_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "tenant":
        return
    # ALTER TABLE (add_column) does not honour the schema_translate_map the way create_table does,
    # so target the real tenant schema name directly (validated first).
    schema = current_schema() or ""
    validate_schema_name(schema)
    # Tag how a candidate was found (reverse-image scan, keyword, or an impersonation name sweep)
    # and an optional per-candidate suggested claim (name sweeps suggest `impersonation`).
    op.add_column(
        "discovery_candidates",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="reverse"),
        schema=schema,
    )
    op.add_column(
        "discovery_candidates",
        sa.Column("suggested_claim", sa.String(length=20), nullable=True),
        schema=schema,
    )
    # Optional second reverse-image engine via SerpApi: off | yandex_images | bing.
    op.add_column(
        "discovery_settings",
        sa.Column(
            "second_reverse_engine", sa.String(length=20), nullable=False, server_default="off"
        ),
        schema=schema,
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = current_schema() or ""
    validate_schema_name(schema)
    op.drop_column("discovery_settings", "second_reverse_engine", schema=schema)
    op.drop_column("discovery_candidates", "suggested_claim", schema=schema)
    op.drop_column("discovery_candidates", "source", schema=schema)
