"""audit_log is append-only: UPDATE and DELETE are rejected for every role.

A BEFORE UPDATE/DELETE trigger enforces this regardless of DB privileges, so it holds even
while the app connects as the table owner (the non-owner `vg_app` role is a tracked
follow-up in docs/BACKLOG.md). Backs the immutability guarantee behind CLAUDE.md #6.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from api.app.audit.service import record_audit
from api.app.db.session import get_engine, tenant_session
from api.app.models.audit import AuditLog
from api.tests.conftest import Fixtures


def test_update_and_delete_are_rejected(db: Fixtures) -> None:
    schema = db.workspace_a.schema_name
    with tenant_session(schema) as session:
        record_audit(
            session,
            workspace_id=db.workspace_a.id,
            action="immutable-probe",
            entity_type="test",
        )

    engine = get_engine()
    with engine.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text(f'UPDATE "{schema}".audit_log SET action = \'tampered\''))
        conn.rollback()
        with pytest.raises(DBAPIError):
            conn.execute(text(f'DELETE FROM "{schema}".audit_log'))
        conn.rollback()

    # The row survived, unchanged.
    with tenant_session(schema) as session:
        actions = set(session.scalars(select(AuditLog.action)).all())
    assert "immutable-probe" in actions
    assert "tampered" not in actions
