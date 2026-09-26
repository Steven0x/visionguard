"""Tenant-schema tables for Slice 7: sealed evidence captures, their artifacts, and the
append-only chain-of-custody log. Evidence is write-once (CLAUDE.md #6)."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class CaptureKind(enum.StrEnum):
    auto = "auto"
    recapture = "recapture"
    proof_of_removal = "proof_of_removal"
    manual_upload = "manual_upload"


class CaptureStatus(enum.StrEnum):
    pending = "pending"
    sealed = "sealed"
    failed = "failed"


class TimestampStatus(enum.StrEnum):
    ok = "ok"
    untimestamped = "untimestamped"


class CustodyAction(enum.StrEnum):
    captured = "captured"
    accessed = "accessed"
    downloaded = "downloaded"
    exported = "exported"
    verified = "verified"


class EvidenceCapture(TenantBase):
    __tablename__ = "evidence_captures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[CaptureKind] = mapped_column(String(20), nullable=False)
    status: Mapped[CaptureStatus] = mapped_column(
        String(20), nullable=False, default=CaptureStatus.pending
    )
    # Sensitive by default (CLAUDE.md #7): blurred/excluded from PDF unless an admin opts in.
    sensitive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    requested_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    visible_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    capture_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    capture_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    captured_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp_status: Mapped[TimestampStatus | None] = mapped_column(String(20), nullable=True)
    tsa_url: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tsa_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvidenceArtifact(TenantBase):
    __tablename__ = "evidence_artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    capture_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_captures.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CustodyEvent(TenantBase):
    __tablename__ = "custody_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    capture_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence_captures.id", ondelete="SET NULL"), nullable=True
    )
    case_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[CustodyAction] = mapped_column(String(20), nullable=False)
    actor_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
