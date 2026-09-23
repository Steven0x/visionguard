"""The acceptance gate: a query in workspace A cannot read workspace B's data.

Proves CLAUDE.md non-negotiable #5 for the audit_log tenant table.
"""

from __future__ import annotations

from sqlalchemy import select

from api.app.audit.service import record_audit
from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.tests.conftest import Fixtures


def _actions_in(schema: str) -> set[str]:
    with tenant_session(schema) as session:
        return set(session.scalars(select(AuditLog.action)).all())


def test_workspace_cannot_read_another_workspaces_audit_log(db: Fixtures) -> None:
    schema_a = db.workspace_a.schema_name
    schema_b = db.workspace_b.schema_name

    with tenant_session(schema_a) as session:
        record_audit(
            session,
            workspace_id=db.workspace_a.id,
            action="a-secret",
            entity_type="test",
        )
    with tenant_session(schema_b) as session:
        record_audit(
            session,
            workspace_id=db.workspace_b.id,
            action="b-secret",
            entity_type="test",
        )

    actions_a = _actions_in(schema_a)
    actions_b = _actions_in(schema_b)

    # Each schema sees its own row and never the other's.
    assert "a-secret" in actions_a
    assert "a-secret" not in actions_b
    assert "b-secret" in actions_b
    assert "b-secret" not in actions_a


def test_row_lands_in_the_bound_schema_only(db: Fixtures) -> None:
    schema_a = db.workspace_a.schema_name
    schema_b = db.workspace_b.schema_name

    with tenant_session(schema_a) as session:
        record_audit(
            session,
            workspace_id=db.workspace_a.id,
            action="isolation-probe",
            entity_type="test",
        )

    with tenant_session(schema_b) as session:
        leaked = session.scalar(
            select(AuditLog).where(AuditLog.action == "isolation-probe")
        )
    assert leaked is None
