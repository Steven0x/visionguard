"""Shared helpers for storing and signing record documents."""

from __future__ import annotations

from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.storage import get_storage
from api.app.storage.keys import object_key


def store_document(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    schema: str,
    kind: str,
    entity_type: str,
    data: bytes,
    content_type: str,
) -> str:
    """Put a document in object storage under an unguessable tenant key; audit the upload."""
    key = object_key(schema, kind, content_type)
    get_storage().put_object(key, data, content_type)
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="document.uploaded",
        entity_type=entity_type,
        meta={"content_type": content_type},
    )
    return key


def signed_download_url(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    entity_type: str,
    entity_id: int,
    file_key: str,
    file_name: str,
) -> str:
    """Issue a short-lived presigned GET URL after the caller has been authorized; audit it."""
    url = get_storage().generate_download_url(
        file_key,
        filename=file_name,
        expires_in=get_settings().storage_signed_url_ttl_seconds,
    )
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="document.downloaded",
        entity_type=entity_type,
        entity_id=str(entity_id),
    )
    return url
