"""Tenant-schema tables for Slice 6: cases, their event timeline, and append-only notes.

The case service (services/cases.py) is the ONLY code that changes ``Case.status``; every
transition appends a ``CaseEvent`` (the timeline) and an audit entry.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class CaseStatus(enum.StrEnum):
    discovered = "discovered"
    confirmed = "confirmed"
    dismissed = "dismissed"
    filed = "filed"
    removed = "removed"
    countered = "countered"
    escalated = "escalated"
    withdrawn = "withdrawn"
    monitoring = "monitoring"
    recovered = "recovered"
    closed = "closed"


# Terminal states have no outgoing transitions and don't count as an "open" case.
TERMINAL_STATES: frozenset[CaseStatus] = frozenset(
    {CaseStatus.dismissed, CaseStatus.withdrawn, CaseStatus.recovered, CaseStatus.closed}
)


class CaseEventKind(enum.StrEnum):
    created = "created"
    transition = "transition"
    claim_change = "claim_change"
    assignment = "assignment"
    link = "link"  # links this case to a related case (e.g. withdrawn ↔ re-filed)


class Case(TenantBase):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    # Retention guard prevents deleting a referenced candidate; SET NULL is a safety valve.
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_candidates.id", ondelete="SET NULL"), nullable=True
    )
    matched_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[CaseStatus] = mapped_column(
        String(20), nullable=False, default=CaseStatus.confirmed
    )
    # Canonical source URL + its sha256 key, copied from the candidate for dedupe/grouping.
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    offender_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Public Staff ids — no cross-schema FK (mirrors audit_log.actor_staff_id).
    opened_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Follow-up timer for the current state (cleared on terminal states).
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CaseEvent(TenantBase):
    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[CaseEventKind] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The other case in a `link` event (e.g. the withdrawn/re-filed counterpart).
    related_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"), nullable=True
    )
    actor_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CaseNote(TenantBase):
    __tablename__ = "case_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    author_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
