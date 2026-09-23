"""Tenant-schema tables for Slice 1: protected subjects and the workspace allowlist."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class SubjectStatus(enum.StrEnum):
    active = "active"
    archived = "archived"


class AllowlistKind(enum.StrEnum):
    domain = "domain"
    handle = "handle"
    url = "url"
    account = "account"


class Subject(TenantBase):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    stage_names: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    handles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    residence_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # Derived server-side (fail closed); never set from client input. See services/subjects.py.
    biometrics_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    status: Mapped[SubjectStatus] = mapped_column(
        String(20), nullable=False, default=SubjectStatus.active
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AllowlistEntry(TenantBase):
    __tablename__ = "allowlist_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[AllowlistKind] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
