"""Tenant-schema tables for Slice 5: case stubs and labeled review decisions.

A ``Case`` here is a stub (status ``confirmed`` only); the full state machine + timeline land
in Slice 6. A ``ReviewDecision`` is an immutable labeled example for a future classifier and is
deliberately decoupled from the candidate (FK SET NULL + snapshot columns) so training data
survives candidate/thumbnail cleanup.
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
    # Slice 5 only creates confirmed stubs; the rest of the lifecycle is Slice 6.
    confirmed = "confirmed"


class ReviewDecisionKind(enum.StrEnum):
    confirm = "confirm"
    dismiss = "dismiss"
    reopen = "reopen"


class DismissReason(enum.StrEnum):
    not_a_match = "not_a_match"
    licensed = "licensed"
    fair_use = "fair_use"
    own_account = "own_account"
    allowlisted = "allowlisted"  # system-only (allowlist auto-dismiss); humans can't pick it
    other = "other"


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
    # Public Staff id — no cross-schema FK (mirrors audit_log.actor_staff_id).
    opened_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReviewDecision(TenantBase):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # SET NULL so a purged candidate doesn't take its training label with it.
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_candidates.id", ondelete="SET NULL"), nullable=True
    )
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[ReviewDecisionKind] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    claim_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
