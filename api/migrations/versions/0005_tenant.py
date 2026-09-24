"""tenant schema: rights_records, consent_records, agent_authorizations

Revision ID: 0005_tenant
Revises: 0004_tenant
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.base import TENANT_SCHEMA_TOKEN
from api.app.db.migration_scope import current_scope

revision: str = "0005_tenant"
down_revision: str | None = "0004_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_FK = f"{TENANT_SCHEMA_TOKEN}.subjects.id"


def _revoke_columns() -> list[sa.Column]:
    return [
        sa.Column("revoked_reason", sa.String(length=500), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_staff_id", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    if current_scope() != "tenant":
        return

    op.create_table(
        "rights_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column(
            "grants_enforcement_right",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("file_key", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("rights_date", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("coverage", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        *_revoke_columns(),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )

    op.create_table(
        "consent_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("file_key", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("signer_name", sa.String(length=200), nullable=False),
        sa.Column("signed_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        *_revoke_columns(),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )

    op.create_table(
        "agent_authorizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("file_key", sa.String(length=500), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("signer_name", sa.String(length=200), nullable=False),
        sa.Column("authorized_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        *_revoke_columns(),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], [_SUBJECT_FK], ondelete="CASCADE"),
        schema=TENANT_SCHEMA_TOKEN,
    )


def downgrade() -> None:
    if current_scope() != "tenant":
        return
    op.drop_table("agent_authorizations", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("consent_records", schema=TENANT_SCHEMA_TOKEN)
    op.drop_table("rights_records", schema=TENANT_SCHEMA_TOKEN)
