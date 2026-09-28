"""public schema: channels.response_window_days (per-platform follow-up window)

Revision ID: 0017_public
Revises: 0016_tenant
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.migration_scope import current_scope

revision: str = "0017_public"
down_revision: str | None = "0016_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seed follow-up windows (days) per platform — how long each usually takes to respond. Ops can
# tune these later via the admin channel API; NULL falls back to case_due_days_map["filed"].
_WINDOWS: dict[str, int] = {
    "generic_host": 10,
    "instagram": 7,
    "facebook": 7,
    "tiktok": 7,
    "x": 5,
    "google_search": 30,
    "amazon": 14,
}


def upgrade() -> None:
    if current_scope() != "public":
        return
    op.add_column(
        "channels", sa.Column("response_window_days", sa.Integer(), nullable=True)
    )
    for platform, days in _WINDOWS.items():
        op.execute(
            sa.text(
                "UPDATE channels SET response_window_days = :days WHERE platform = :platform"
            ).bindparams(days=days, platform=platform)
        )


def downgrade() -> None:
    if current_scope() != "public":
        return
    op.drop_column("channels", "response_window_days")
