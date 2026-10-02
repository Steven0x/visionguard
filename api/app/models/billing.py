"""Public-schema billing tables (Slice 13).

These hold only Stripe IDs and per-workspace plan config — the same altitude as the ``workspaces``
row, no subject/case/evidence data — so they live in the PUBLIC schema and the per-tenant isolation
rule (CLAUDE.md #5) does not apply. Billing AUDIT rows still land in the tenant ``audit_log`` via a
tenant session. Stripe is the source of truth; these columns are a thin, reconciled mirror.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import PublicBase


class BillingMode(enum.StrEnum):
    # Invoiced outside Stripe (design partners, demos, legacy) — EXEMPT from every billing gate.
    manual = "manual"
    # Stripe subscription billing — the gates in services/billing.py apply.
    stripe = "stripe"


class BillingStatus(enum.StrEnum):
    none = "none"  # stripe mode, never subscribed → suspended until Checkout completes
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"


class PlanTier(enum.StrEnum):
    none = "none"
    core = "core"
    priority = "priority"


class BillingCadence(enum.StrEnum):
    none = "none"
    monthly = "monthly"
    annual = "annual"


class WorkspaceBilling(PublicBase):
    __tablename__ = "workspace_billing"

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    billing_mode: Mapped[BillingMode] = mapped_column(
        String(20), nullable=False, default=BillingMode.manual, server_default="manual"
    )
    # One Stripe customer per workspace, created server-side before Checkout. Unique so webhook
    # data can never re-map a customer to a different workspace.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[BillingStatus] = mapped_column(
        String(20), nullable=False, default=BillingStatus.none, server_default="none"
    )
    plan_tier: Mapped[PlanTier] = mapped_column(
        String(20), nullable=False, default=PlanTier.none, server_default="none"
    )
    cadence: Mapped[BillingCadence] = mapped_column(
        String(20), nullable=False, default=BillingCadence.none, server_default="none"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Stamped the FIRST time past_due is observed; never reset on replay/re-fetch; cleared only when
    # status leaves past_due/canceled. grace_until = past_due_since + billing_grace_days.
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The one agency user who manages billing from the portal.
    billing_contact_staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("staff.id", ondelete="SET NULL"), nullable=True
    )

    # Set once when the $1,500 onboarding audit is credited toward the first month (idempotent).
    onboarding_credit_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    design_partner_coupon_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Admin feature overrides. NULL = no override (use the plan). priority_override forces the
    # priority feature set on/off; discovery_frequency_override forces a max ScanFrequency value.
    priority_override: Mapped[bool | None] = mapped_column(nullable=True)
    discovery_frequency_override: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BillingEvent(PublicBase):
    """Webhook idempotency ledger — one row per processed Stripe event id."""

    __tablename__ = "billing_events"

    stripe_event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
