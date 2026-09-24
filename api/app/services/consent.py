"""Consent-record services. Revoking a biometric consent fires the purge hook."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.models.rights import ConsentRecord, ConsentType, RecordStatus
from api.app.services.biometrics import purge_biometric_data
from api.app.services.documents import audit_upload, signed_download_url, store_document


def list_consent(session: Session, subject_id: int) -> list[ConsentRecord]:
    return list(
        session.scalars(
            select(ConsentRecord)
            .where(ConsentRecord.subject_id == subject_id)
            .order_by(ConsentRecord.id)
        ).all()
    )


def get_consent(session: Session, consent_id: int) -> ConsentRecord | None:
    return session.get(ConsentRecord, consent_id)


def create_consent_record(
    session: Session,
    *,
    workspace_id: int,
    schema: str,
    actor_staff_id: int | None,
    subject_id: int,
    type: ConsentType,
    data: bytes,
    content_type: str,
    file_name: str,
    signer_name: str,
    signed_date: date,
) -> ConsentRecord:
    key = store_document(schema, "consent", data, content_type)
    record = ConsentRecord(
        subject_id=subject_id,
        type=type,
        file_key=key,
        file_name=file_name,
        content_type=content_type,
        signer_name=signer_name,
        signed_date=signed_date,
        status=RecordStatus.active,
    )
    session.add(record)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="consent.created",
        entity_type="consent_record",
        entity_id=str(record.id),
        meta={"type": str(type)},
    )
    audit_upload(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        entity_type="consent_record",
        entity_id=record.id,
        content_type=content_type,
    )
    return record


def revoke_consent(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    record: ConsentRecord,
    reason: str | None,
) -> ConsentRecord:
    if record.status == RecordStatus.revoked:
        return record  # idempotent: don't re-fire the purge or duplicate the audit
    record.status = RecordStatus.revoked
    record.revoked_reason = reason
    record.revoked_at = datetime.now(UTC)
    record.revoked_by_staff_id = actor_staff_id
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="consent.revoked",
        entity_type="consent_record",
        entity_id=str(record.id),
    )
    # Revoking biometric consent must hard-delete the subject's biometric data — but only
    # once NO active biometric consent remains for that subject.
    if record.type == ConsentType.biometric and not _has_active_biometric_consent(
        session, record.subject_id
    ):
        purged = purge_biometric_data(session, record.subject_id)
        record_audit(
            session,
            workspace_id=workspace_id,
            actor_staff_id=actor_staff_id,
            action="biometrics.purged",
            entity_type="subject",
            entity_id=str(record.subject_id),
            meta={"deleted": purged},
        )
    return record


def _has_active_biometric_consent(session: Session, subject_id: int) -> bool:
    return (
        session.scalar(
            select(ConsentRecord.id)
            .where(
                ConsentRecord.subject_id == subject_id,
                ConsentRecord.type == ConsentType.biometric,
                ConsentRecord.status == RecordStatus.active,
            )
            .limit(1)
        )
        is not None
    )


def consent_download_url(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    record: ConsentRecord,
) -> str:
    return signed_download_url(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        entity_type="consent_record",
        entity_id=record.id,
        file_key=record.file_key,
        file_name=record.file_name,
    )
