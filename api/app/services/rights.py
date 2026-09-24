"""Rights-record services: create (with document), list, revoke, signed download."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.models.rights import RightsRecord, RightsStatus, RightsType
from api.app.services.documents import signed_download_url, store_document


def list_rights(session: Session, subject_id: int) -> list[RightsRecord]:
    return list(
        session.scalars(
            select(RightsRecord)
            .where(RightsRecord.subject_id == subject_id)
            .order_by(RightsRecord.id)
        ).all()
    )


def get_rights(session: Session, rights_id: int) -> RightsRecord | None:
    return session.get(RightsRecord, rights_id)


def create_rights_record(
    session: Session,
    *,
    workspace_id: int,
    schema: str,
    actor_staff_id: int | None,
    subject_id: int,
    type: RightsType,
    grants_enforcement_right: bool,
    data: bytes,
    content_type: str,
    file_name: str,
    rights_date: date | None = None,
    expires_on: date | None = None,
    coverage: str | None = None,
    notes: str | None = None,
) -> RightsRecord:
    key = store_document(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        schema=schema,
        kind="rights",
        entity_type="rights_record",
        data=data,
        content_type=content_type,
    )
    record = RightsRecord(
        subject_id=subject_id,
        type=type,
        grants_enforcement_right=grants_enforcement_right,
        file_key=key,
        file_name=file_name,
        content_type=content_type,
        rights_date=rights_date,
        expires_on=expires_on,
        coverage=coverage,
        notes=notes,
        status=RightsStatus.active,
    )
    session.add(record)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="rights.created",
        entity_type="rights_record",
        entity_id=str(record.id),
        meta={"type": str(type)},
    )
    return record


def revoke_rights(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    record: RightsRecord,
    reason: str | None,
) -> RightsRecord:
    record.status = RightsStatus.revoked
    record.revoked_reason = reason
    record.revoked_at = datetime.now(UTC)
    record.revoked_by_staff_id = actor_staff_id
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="rights.revoked",
        entity_type="rights_record",
        entity_id=str(record.id),
    )
    return record


def rights_download_url(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    record: RightsRecord,
) -> str:
    return signed_download_url(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        entity_type="rights_record",
        entity_id=record.id,
        file_key=record.file_key,
        file_name=record.file_name,
    )
