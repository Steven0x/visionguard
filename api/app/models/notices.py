"""Tenant-schema tables for Slice 8: notices, their append-only version history, and the
filing log. The notices service (services/notices.py) is the only mutator; every draft/edit/
approve/send/withdraw writes an audit entry, and the exact sent notice is sealed write-once via
the evidence machinery (CaptureKind.notice). See docs/specs/notices.md."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class NoticeStatus(enum.StrEnum):
    draft = "draft"
    sent = "sent"
    # Recorded + case Filed, but the email transport failed after commit — visible retry state.
    delivery_failed = "delivery_failed"
    withdrawn = "withdrawn"


class FilingOutcome(enum.StrEnum):
    sent = "sent"  # email notice sent
    submitted_by_hand = "submitted_by_hand"  # web_form/portal, recorded after hand-submission
    withdrawn = "withdrawn"


class Notice(TenantBase):
    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    # References to public reference data — plain ints, no cross-schema FK.
    channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
    template_id: Mapped[int] = mapped_column(Integer, nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NoticeStatus] = mapped_column(
        String(20), nullable=False, default=NoticeStatus.draft
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Set on send: the sealed EvidenceCapture (kind=notice) holding the exact sent text.
    sealed_capture_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The version the human approved. An edit bumps current_version, so a stale approval (an edit
    # after approval) is caught at send time — approval binds to exact content (CLAUDE.md #3).
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Recorded with the approval: the approver ticked "I considered fair use". Required to send a
    # copyright notice (Lenz v. Universal). Reset by any edit (which invalidates the approval).
    fair_use_considered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class NoticeVersion(TenantBase):
    """Append-only draft history: a new row on every edit (no update/delete path)."""

    __tablename__ = "notice_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("notices.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FilingLog(TenantBase):
    __tablename__ = "filing_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    notice_id: Mapped[int | None] = mapped_column(
        ForeignKey("notices.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[FilingOutcome] = mapped_column(String(30), nullable=False)
    ticket_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    filed_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
