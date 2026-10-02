"""public schema: billing (workspace_billing + billing_events) — Slice 13

Revision ID: 0021_public
Revises: 0020_tenant
Create Date: 2026-10-01

Public-schema only (Stripe IDs + per-workspace plan mirror; no tenant data). Every EXISTING
workspace gets a workspace_billing row at billing_mode='manual' so nothing breaks on rollout —
manual mode is exempt from all billing gates.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.migration_scope import current_scope

revision: str = "0021_public"
down_revision: str | None = "0020_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if current_scope() != "public":
        return

    op.create_table(
        "workspace_billing",
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "billing_mode", sa.String(length=20), nullable=False, server_default="manual"
        ),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("plan_tier", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("cadence", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "billing_contact_staff_id",
            sa.Integer(),
            sa.ForeignKey("staff.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("onboarding_credit_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("design_partner_coupon_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority_override", sa.Boolean(), nullable=True),
        sa.Column("discovery_frequency_override", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # One Stripe customer per workspace — never re-mapped across workspaces.
        sa.UniqueConstraint("stripe_customer_id", name="uq_workspace_billing_stripe_customer"),
    )

    op.create_table(
        "billing_events",
        sa.Column("stripe_event_id", sa.String(length=255), primary_key=True),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # Back-fill a manual-mode billing row for every existing workspace (gates skip manual).
    op.execute(
        sa.text(
            "INSERT INTO workspace_billing (workspace_id, billing_mode) "
            "SELECT id, 'manual' FROM workspaces"
        )
    )


def downgrade() -> None:
    if current_scope() != "public":
        return
    op.drop_table("billing_events")
    op.drop_table("workspace_billing")
