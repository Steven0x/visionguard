"""custody_events is append-only: UPDATE and DELETE are rejected (CLAUDE.md #6), same guarantee
as audit_log — a BEFORE UPDATE/DELETE trigger enforces it regardless of DB privileges."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from api.app.db.session import get_engine, tenant_session
from api.app.models.evidence import CustodyAction, CustodyEvent
from api.tests.conftest import Fixtures


def test_custody_update_and_delete_are_rejected(db: Fixtures) -> None:
    schema = db.workspace_a.schema_name
    with tenant_session(schema) as session:
        session.add(
            CustodyEvent(case_id=1, capture_id=None, action=CustodyAction.captured,
                         detail="immutable-probe")
        )

    engine = get_engine()
    with engine.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text(f'UPDATE "{schema}".custody_events SET detail = \'tampered\''))
        conn.rollback()
        with pytest.raises(DBAPIError):
            conn.execute(text(f'DELETE FROM "{schema}".custody_events'))
        conn.rollback()

    with tenant_session(schema) as session:
        details = set(session.scalars(select(CustodyEvent.detail)).all())
    assert "immutable-probe" in details and "tampered" not in details
