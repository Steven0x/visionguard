"""tenant schema: cases.page_url (offender page URL, for the send-time allowlist re-check)

Revision ID: 0016_tenant
Revises: 0015_tenant
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from api.app.db.base import validate_schema_name
from api.app.db.migration_scope import current_schema, current_scope

revision: str = "0016_tenant"
down_revision: str | None = "0015_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "tenant":
        return
    # ALTER goes through raw SQL against the validated real schema (schema_translate_map does not
    # rewrite it), matching the pattern in 0011_tenant.
    schema = validate_schema_name(current_schema() or "")
    op.execute(f'ALTER TABLE "{schema}".cases ADD COLUMN page_url TEXT')


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    schema = validate_schema_name(current_schema() or "")
    op.execute(f'ALTER TABLE "{schema}".cases DROP COLUMN IF EXISTS page_url')
