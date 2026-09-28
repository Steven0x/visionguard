"""Tenant-schema table for Slice 10: generated agency reports.

A ``Report`` is an append-only record of a report VisionGuard staff generated for an agency
(whole workspace or one subject, over a date range). The rendered PDF and a JSON snapshot of its
inputs are sealed write-once in the object-locked evidence bucket; this row stores their keys and
SHA-256s so the report can be regenerated and checked later. The reports service
(services/reports.py) is the only writer. See docs/specs/reports.md, ADR 0013."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class Report(TenantBase):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Null = whole-workspace report; set = a single subject. No cross-schema FK (plain int), like
    # other tenant tables that reference public/other ids.
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # The instant the numbers were computed — the report is reproducible "as of" this time.
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    include_thumbnails: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Sealed write-once artifacts (evidence bucket) + their content hashes (integrity anchor).
    pdf_key: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    json_key: Mapped[str] = mapped_column(Text, nullable=False)
    json_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
