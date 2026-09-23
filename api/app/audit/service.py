"""Append-only audit helper. Write one row on a tenant session; never update or delete."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.app.models.audit import AuditLog


def record_audit(
    session: Session,
    *,
    workspace_id: int,
    action: str,
    entity_type: str,
    actor_staff_id: int | None = None,
    entity_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditLog:
    """Insert an audit row (who / what / when / workspace / entity) and return it.

    ``session`` must be a tenant session (bound to the workspace's schema), so the row
    lands in that workspace's ``audit_log`` and nowhere else.
    """
    entry = AuditLog(
        workspace_id=workspace_id,
        action=action,
        entity_type=entity_type,
        actor_staff_id=actor_staff_id,
        entity_id=entity_id,
        meta=meta,
    )
    session.add(entry)
    session.flush()
    return entry
