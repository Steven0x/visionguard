"""Tenant-schema table for Slice 12: agency-portal submissions awaiting staff review.

Both agency write actions land here so staff have one queue: a URL tip (also fanned out to the
discovery review inbox as a pending candidate) and a "Needs from you" answer (text and/or a
quarantined, CSAM-scanned PDF). Nothing here is a legal-basis record — staff verify a submission
and create the real rights/consent record by hand (human-in-the-loop, CLAUDE.md #3)."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class SubmissionKind(enum.StrEnum):
    url_tip = "url_tip"
    needs_response = "needs_response"


class SubmissionStatus(enum.StrEnum):
    new = "new"
    reviewed = "reviewed"
    dismissed = "dismissed"


class PortalSubmission(TenantBase):
    __tablename__ = "portal_submissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[SubmissionKind] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # For needs_response: which "Needs from you" bucket the agency answered.
    need_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For url_tip: the submitted URL (canonicalized copy is on the discovery candidate).
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For needs_response with a file: the quarantined object key + original name (staff download).
    file_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        String(20), nullable=False, default=SubmissionStatus.new
    )
    # Public Staff ids — no cross-schema FK (mirrors audit_log / cases).
    submitted_by_staff_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_by_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
