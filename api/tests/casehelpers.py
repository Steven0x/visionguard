"""Helpers for Slice 6 case tests: build cases directly at a chosen state."""

from __future__ import annotations

from datetime import UTC, datetime

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.evidence import (
    CaptureKind,
    CaptureStatus,
    EvidenceCapture,
    TimestampStatus,
)


def make_case(
    schema: str,
    subject_id: int,
    *,
    status: CaseStatus = CaseStatus.confirmed,
    claim_type: str = "likeness",
    source_key: str | None = None,
    source_url: str | None = None,
    page_url: str | None = None,
    offender_key: str | None = None,
    candidate_id: int | None = None,
    matched_asset_id: int | None = None,
    due_at: datetime | None = None,
) -> int:
    with tenant_session(schema) as session:
        case = Case(
            subject_id=subject_id,
            claim_type=claim_type,
            status=status,
            source_key=source_key,
            source_url=source_url,
            page_url=page_url,
            offender_key=offender_key,
            candidate_id=candidate_id,
            matched_asset_id=matched_asset_id,
            due_at=due_at,
        )
        session.add(case)
        session.flush()
        return case.id


def past_due() -> datetime:
    return datetime(2020, 1, 1, tzinfo=UTC)


def seal_capture(schema: str, case_id: int) -> int:
    """Insert a fresh sealed evidence capture so the case satisfies the → filed gate."""
    with tenant_session(schema) as session:
        capture = EvidenceCapture(
            case_id=case_id,
            kind=CaptureKind.auto,
            status=CaptureStatus.sealed,
            capture_finished_at=datetime.now(UTC),
            manifest_sha256="0" * 64,
            timestamp_status=TimestampStatus.ok,
        )
        session.add(capture)
        session.flush()
        return capture.id
