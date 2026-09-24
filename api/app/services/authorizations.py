"""Agent-authorization services. An active authorization is the enforceability gate."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.models.rights import AgentAuthorization, RecordStatus
from api.app.services.documents import audit_upload, store_document


def list_authorizations(
    session: Session, *, subject_id: int | None = None, workspace_level_only: bool = False
) -> list[AgentAuthorization]:
    stmt = select(AgentAuthorization).order_by(AgentAuthorization.id)
    if workspace_level_only:
        stmt = stmt.where(AgentAuthorization.subject_id.is_(None))
    elif subject_id is not None:
        stmt = stmt.where(AgentAuthorization.subject_id == subject_id)
    return list(session.scalars(stmt).all())


def get_authorization(session: Session, authorization_id: int) -> AgentAuthorization | None:
    return session.get(AgentAuthorization, authorization_id)


def active_authorization(
    session: Session, subject_id: int
) -> AgentAuthorization | None:
    """An active authorization that covers this subject: workspace-level OR subject-level.

    Deterministic: prefer a subject-level authorization over a workspace-level one, then the
    newest, so ``subject_enforcement`` reports a stable, meaningful authorization id.
    """
    return session.scalar(
        select(AgentAuthorization)
        .where(
            AgentAuthorization.status == RecordStatus.active,
            or_(
                AgentAuthorization.subject_id.is_(None),
                AgentAuthorization.subject_id == subject_id,
            ),
        )
        .order_by(
            AgentAuthorization.subject_id.is_(None),  # False (subject-level) first
            AgentAuthorization.id.desc(),
        )
        .limit(1)
    )


def create_authorization(
    session: Session,
    *,
    workspace_id: int,
    schema: str,
    actor_staff_id: int | None,
    subject_id: int | None,
    signer_name: str,
    authorized_date: date,
    notes: str | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    file_name: str | None = None,
) -> AgentAuthorization:
    file_key: str | None = None
    if data is not None and content_type is not None:
        file_key = store_document(schema, "authorization", data, content_type)
    record = AgentAuthorization(
        subject_id=subject_id,
        file_key=file_key,
        file_name=file_name,
        content_type=content_type,
        signer_name=signer_name,
        authorized_date=authorized_date,
        notes=notes,
        status=RecordStatus.active,
    )
    session.add(record)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="authorization.created",
        entity_type="agent_authorization",
        entity_id=str(record.id),
        meta={"scope": "workspace" if subject_id is None else "subject"},
    )
    if file_key is not None and content_type is not None:
        audit_upload(
            session,
            workspace_id=workspace_id,
            actor_staff_id=actor_staff_id,
            entity_type="agent_authorization",
            entity_id=record.id,
            content_type=content_type,
        )
    return record


def revoke_authorization(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    record: AgentAuthorization,
    reason: str | None,
) -> AgentAuthorization:
    if record.status == RecordStatus.revoked:
        return record  # idempotent
    record.status = RecordStatus.revoked
    record.revoked_reason = reason
    record.revoked_at = datetime.now(UTC)
    record.revoked_by_staff_id = actor_staff_id
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="authorization.revoked",
        entity_type="agent_authorization",
        entity_id=str(record.id),
    )
    return record


