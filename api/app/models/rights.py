"""Tenant-schema tables for Slice 2: rights, consent, and agent-authorization records."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class RightsType(enum.StrEnum):
    management_agreement = "management_agreement"
    photographer_license = "photographer_license"
    copyright_registration = "copyright_registration"
    self_owned_declaration = "self_owned_declaration"
    other = "other"


class RightsStatus(enum.StrEnum):
    active = "active"
    expired = "expired"
    revoked = "revoked"


class ConsentType(enum.StrEnum):
    enforcement = "enforcement"
    biometric = "biometric"


class RecordStatus(enum.StrEnum):
    active = "active"
    revoked = "revoked"


class RightsRecord(TenantBase):
    __tablename__ = "rights_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[RightsType] = mapped_column(String(40), nullable=False)
    # Must be true for a photographer_license to support copyright (representation ≠ ownership).
    grants_enforcement_right: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    rights_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    coverage: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RightsStatus] = mapped_column(
        String(20), nullable=False, default=RightsStatus.active
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConsentRecord(TenantBase):
    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[ConsentType] = mapped_column(String(20), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    signed_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        String(20), nullable=False, default=RecordStatus.active
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentAuthorization(TenantBase):
    __tablename__ = "agent_authorizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL ⇒ workspace-level authorization; set ⇒ authorization for that specific subject.
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True
    )
    # Document is optional — a staff attestation (signer + date) is sufficient in Phase 1.
    file_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    authorized_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        String(20), nullable=False, default=RecordStatus.active
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
