"""Public-schema reference data for Slice 8: the channel registry and notice templates.

These are VisionGuard-wide, not per-tenant: staff serve every agency and counsel approves each
template once for all of them (see docs/adr/0011-notices-channels-templates.md). Routing obeys
docs/legal/claims-matrix.md — a `trademark`/`likeness` row may never use an email/DMCA channel.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import PublicBase


class ChannelMethod(enum.StrEnum):
    email = "email"  # rendered notice sent via SendGrid/outbox, then sealed
    web_form = "web_form"  # copy-ready packet; staff submit by hand
    portal = "portal"  # copy-ready packet; staff submit in a platform portal


class TemplateApproval(enum.StrEnum):
    unapproved = "unapproved"
    counsel_approved = "counsel_approved"


class Channel(PublicBase):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("platform", "claim_type", name="uq_channel_platform_claim"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[ChannelMethod] = mapped_column(String(20), nullable=False)
    # DMCA-agent / abuse email for `email`; the form URL for `web_form`/`portal`.
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    # Context keys the notice/packet must contain for this channel.
    required_fields: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NoticeTemplate(PublicBase):
    __tablename__ = "notice_templates"
    __table_args__ = (
        UniqueConstraint("claim_type", "method", name="uq_template_claim_method"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[ChannelMethod] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    # Claims-matrix elements the notice must contain (e.g. the DMCA §512(c)(3) items).
    required_elements: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    approval_status: Mapped[TemplateApproval] = mapped_column(
        String(20), nullable=False, default=TemplateApproval.unapproved
    )
    # Approval is a global action; audit_log is tenant-scoped, so the on-row record is the
    # durable proof (see ADR 0011).
    approved_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approver_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
