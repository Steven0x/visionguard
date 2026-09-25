"""Tenant-schema tables for Slice 4: discovery settings, runs, and candidates."""

from __future__ import annotations

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase

EMBEDDING_DIM = 512


class ScanFrequency(enum.StrEnum):
    off = "off"
    daily = "daily"
    weekly = "weekly"


class RunKind(enum.StrEnum):
    manual_intake = "manual_intake"
    reverse_image = "reverse_image"
    keyword = "keyword"


class RunStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    partial = "partial"
    blocked = "blocked"
    failed = "failed"


class CandidateKind(enum.StrEnum):
    image = "image"
    link = "link"


class DiscoverySettings(TenantBase):
    __tablename__ = "discovery_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    monthly_call_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    scan_frequency: Mapped[ScanFrequency] = mapped_column(
        String(20), nullable=False, default=ScanFrequency.off
    )
    tineye_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    thumbnail_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DiscoveryRun(TenantBase):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[RunKind] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        String(20), nullable=False, default=RunStatus.running
    )
    calls_made: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DiscoveryCandidate(TenantBase):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint("subject_id", "source_key", name="uq_candidate_source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[CandidateKind] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of the canonical source_url — the dedupe key (avoids indexing huge URLs).
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    thumbnail_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
