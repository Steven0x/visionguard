"""Workspace provisioning: create the public row + its isolated tenant schema.

This is internal plumbing (used by the CLI and tests), not a Slice-0 product feature. The
schema name is always DERIVED from the workspace id and validated before any DDL runs.
"""

from __future__ import annotations

from sqlalchemy import text

from api.app.db.base import schema_for_workspace
from api.app.db.migrate import upgrade_all
from api.app.db.session import get_engine, public_session
from api.app.models.public import Workspace


def create_workspace(
    *,
    name: str,
    slug: str,
    plan: str = "starter",
    contact_name: str | None = None,
    contact_email: str | None = None,
) -> Workspace:
    """Create a workspace and bring its tenant schema to the latest migration head."""
    with public_session() as session:
        workspace = Workspace(
            name=name,
            slug=slug,
            plan=plan,
            contact_name=contact_name,
            contact_email=contact_email,
        )
        session.add(workspace)
        session.flush()
        workspace_id = workspace.id
        session.commit()
        session.refresh(workspace)
        session.expunge(workspace)

    # Derive + validate the schema name from the trusted id, then create it. The name is
    # interpolated only after passing ^ws_[a-z0-9_]+$, so it cannot carry injected SQL.
    schema = schema_for_workspace(workspace_id)
    with get_engine().begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    # Apply tenant migrations (loops all schemas; only the new one has work to do).
    upgrade_all()
    return workspace
