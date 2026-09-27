"""Workspace services: create (with creator access), list, edit, and allowlist management."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.db.base import schema_for_workspace
from api.app.db.session import public_session, tenant_session
from api.app.models.public import Staff, StaffWorkspaceAccess, Workspace
from api.app.models.subjects import AllowlistEntry, AllowlistKind
from api.app.services.provisioning import create_workspace
from api.app.services.staff import grant_workspace_access

# Valid workspace plans (kept in sync with the frontend dropdown in web/src/components).
WORKSPACE_PLANS: tuple[str, ...] = ("starter", "pro", "enterprise")


class DuplicateWorkspace(Exception):
    """Raised when a workspace with the same slug already exists (→ 409)."""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"


def _slug_taken(slug: str) -> bool:
    with public_session() as session:
        return session.scalar(select(Workspace.id).where(Workspace.slug == slug)) is not None


def create_workspace_with_access(
    *,
    name: str,
    creator_staff_id: int,
    plan: str = "starter",
    slug: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
) -> Workspace:
    """Provision a workspace, grant the creator access, and audit `workspace.created`.

    Rejects a duplicate name/slug with DuplicateWorkspace (→ 409) rather than silently
    suffixing. The pre-check is friendly; the unique constraint is the race backstop.
    """
    resolved_slug = slugify(slug or name)
    if _slug_taken(resolved_slug):
        raise DuplicateWorkspace(
            f"a workspace named '{name}' (slug '{resolved_slug}') already exists"
        )
    try:
        workspace = create_workspace(
            name=name,
            slug=resolved_slug,
            plan=plan,
            contact_name=contact_name,
            contact_email=contact_email,
        )
    except IntegrityError as exc:  # concurrent create won the slug between check and insert
        raise DuplicateWorkspace(
            f"a workspace named '{name}' (slug '{resolved_slug}') already exists"
        ) from exc
    grant_workspace_access(staff_id=creator_staff_id, workspace_id=workspace.id)
    with tenant_session(workspace.schema_name) as session:
        record_audit(
            session,
            workspace_id=workspace.id,
            actor_staff_id=creator_staff_id,
            action="workspace.created",
            entity_type="workspace",
            entity_id=str(workspace.id),
        )
    return workspace


def list_accessible(staff: Staff) -> list[Workspace]:
    with public_session() as session:
        stmt = select(Workspace).order_by(Workspace.name, Workspace.id)
        if not staff.all_workspaces:
            stmt = stmt.join(
                StaffWorkspaceAccess,
                StaffWorkspaceAccess.workspace_id == Workspace.id,
            ).where(StaffWorkspaceAccess.staff_id == staff.id)
        workspaces = list(session.scalars(stmt).all())
        for ws in workspaces:
            session.expunge(ws)
        return workspaces


def update_workspace(
    *, workspace_id: int, actor_staff_id: int | None, changes: dict[str, object]
) -> Workspace:
    """Update allowed public columns and audit `workspace.updated`."""
    with public_session() as session:
        workspace = session.get(Workspace, workspace_id)
        if workspace is None:  # pragma: no cover - router checks access/existence first
            raise ValueError("workspace not found")
        for key, value in changes.items():
            setattr(workspace, key, value)
        session.flush()
        session.commit()
        session.refresh(workspace)
        session.expunge(workspace)

    with tenant_session(schema_for_workspace(workspace_id)) as session:
        record_audit(
            session,
            workspace_id=workspace_id,
            actor_staff_id=actor_staff_id,
            action="workspace.updated",
            entity_type="workspace",
            entity_id=str(workspace_id),
            meta={"fields": sorted(changes)},
        )
    return workspace


# ── Allowlist (tenant session passed in by the router) ────────────────────────


def list_allowlist(session: Session) -> list[AllowlistEntry]:
    return list(
        session.scalars(select(AllowlistEntry).order_by(AllowlistEntry.id)).all()
    )


def add_allowlist_entry(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    kind: AllowlistKind,
    value: str,
    note: str | None = None,
) -> AllowlistEntry:
    entry = AllowlistEntry(kind=kind, value=value.strip(), note=note)
    session.add(entry)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="allowlist.entry_added",
        entity_type="allowlist_entry",
        entity_id=str(entry.id),
        # Data minimization (CLAUDE.md #7): log the kind + id, not the value payload.
        meta={"kind": str(kind)},
    )
    return entry


def remove_allowlist_entry(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    entry_id: int,
) -> bool:
    entry = session.get(AllowlistEntry, entry_id)
    if entry is None:
        return False
    session.delete(entry)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="allowlist.entry_removed",
        entity_type="allowlist_entry",
        entity_id=str(entry_id),
    )
    return True
