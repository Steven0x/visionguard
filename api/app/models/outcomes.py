"""Tenant-schema tables for Slice 9: platform-response outcomes and URL re-check history.

Both are append-only (trigger + REVOKE, like ``notice_versions``): a mistaken outcome is
corrected by appending a *superseding* row, never by editing, and every probe is a new row. The
outcomes service (services/outcomes.py) and recheck service (services/recheck.py) are the only
writers. See docs/specs/outcomes.md."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class OutcomeKind(enum.StrEnum):
    removed = "removed"  # content taken down → case filed → removed
    rejected = "rejected"  # platform refused → stays filed; staff escalate or withdraw
    countered = "countered"  # counter-notice → case filed → countered
    no_response = "no_response"  # window elapsed, no reply → stays filed; nudge again


class OutcomeSource(enum.StrEnum):
    manual = "manual"  # staff recorded it
    auto_confirmed = "auto_confirmed"  # staff confirmed an auto-proposed removal


class RecheckResult(enum.StrEnum):
    live = "live"  # 2xx — NEVER proof of anything (soft-404s serve 200)
    gone = "gone"  # 404/410/451 or connection refused
    error = "error"  # 401/403 (login wall), 429 (rate limit), 5xx, timeout — inconclusive


class NoticeOutcome(TenantBase):
    __tablename__ = "notice_outcomes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("notices.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[OutcomeKind] = mapped_column(String(20), nullable=False)
    source: Mapped[OutcomeSource] = mapped_column(
        String(20), nullable=False, default=OutcomeSource.manual
    )
    # When the platform actually acted (content went down). Median time-to-removal uses this, not
    # the confirmation timestamp. Defaults to the earliest consistent `gone` recheck, else today.
    effective_at: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A correcting row points at the outcome it supersedes; the latest non-superseded row wins.
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("notice_outcomes.id", ondelete="SET NULL"), nullable=True
    )
    recorded_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UrlRecheck(TenantBase):
    __tablename__ = "url_rechecks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    # The URL actually probed (page_url primary; source_url only as a fallback).
    probed_url: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[RecheckResult] = mapped_column(String(10), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
