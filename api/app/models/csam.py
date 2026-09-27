"""Tenant-schema table for CSAM matches. NO image bytes are ever stored — only the hash, URL,
and time — and rows route to an admin-only escalation queue for the NCMEC report path
(CLAUDE.md #7)."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class CsamSource(enum.StrEnum):
    discovery = "discovery"
    capture = "capture"
    manual_upload = "manual_upload"
    asset_upload = "asset_upload"


class CsamIncidentStatus(enum.StrEnum):
    open = "open"
    reported = "reported"  # NCMEC report filed
    dismissed = "dismissed"  # reviewed as a false positive


class CsamIncident(TenantBase):
    __tablename__ = "csam_incidents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[CsamSource] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    case_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Minimized evidence only — never the image or a thumbnail.
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[CsamIncidentStatus] = mapped_column(
        String(20), nullable=False, default=CsamIncidentStatus.open
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
