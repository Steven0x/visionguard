"""Workspace provisioning: create the public row + its isolated tenant schema.

This is internal plumbing (used by the CLI and tests), not a Slice-0 product feature. The
schema name is always DERIVED from the workspace id and validated before any DDL runs.
"""

from __future__ import annotations

from sqlalchemy import text

from api.app.db.base import schema_for_workspace
from api.app.db.migrate import upgrade_schema
from api.app.db.session import get_engine, public_session
from api.app.models.public import Workspace

# Serializes provisioning across concurrent creates. upgrade_all() migrates EVERY tenant schema
# and is not safe to run concurrently — two simultaneous creates would each migrate the other's
# freshly-created schema and collide (DuplicateTable). A session-level Postgres advisory lock
# held across schema creation + migration makes provisioning sequential. Arbitrary fixed key.
_PROVISION_LOCK_KEY = 0x76_67_70_72  # "vgpr"


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
    # Hold a session-level advisory lock across CREATE SCHEMA + upgrade_all so concurrent
    # provisions serialize (see _PROVISION_LOCK_KEY). The lock survives commits and is released
    # explicitly / on connection close.
    lock_conn = get_engine().connect()
    try:
        lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _PROVISION_LOCK_KEY})
        lock_conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        lock_conn.commit()
        # Migrate ONLY this new tenant schema (public is already at head).
        upgrade_schema(schema)
    finally:
        lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _PROVISION_LOCK_KEY})
        lock_conn.commit()
        lock_conn.close()
    return workspace
