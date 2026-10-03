"""tenant schema: backfill any stored second_reverse_engine='bing' to 'off'

Bing was removed (no robust SerpApi Bing reverse-by-URL engine; its APIs were retired). The
`SettingsIn` schema now rejects `bing` (422) and the worker treats it as off, but a workspace that
selected it before the removal keeps the now-invalid value (and the UI select renders blank). This
backfills it so stored state never holds a value outside the allowed set (`off | yandex_images`).

Revision ID: 0023_tenant
Revises: 0022_tenant
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0023_tenant"
down_revision: str | None = "0022_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = current_schema() or ""
    validate_schema_name(schema)
    table = sa.table(
        "discovery_settings", sa.column("second_reverse_engine", sa.String), schema=schema
    )
    op.execute(
        table.update()
        .where(table.c.second_reverse_engine == "bing")
        .values(second_reverse_engine="off")
    )


def downgrade() -> None:
    # Not reversible: 'bing' is no longer a valid value, so there is nothing to restore.
    pass
