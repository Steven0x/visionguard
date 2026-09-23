"""Workspace routes: create/list/get/edit, the allowlist, and the Slice-0 sample route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.auth.deps import (
    get_tenant_session,
    require_role,
    require_workspace_access,
)
from api.app.models.audit import AuditLog
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.models.subjects import AllowlistKind
from api.app.services import workspaces as ws_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_ADMIN = require_role(StaffRole.admin)
_STAFF = require_role(StaffRole.admin, StaffRole.reviewer)


# ── Schemas ───────────────────────────────────────────────────────────────────


class WorkspaceCreate(BaseModel):
    name: str
    plan: str = "starter"
    slug: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    plan: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    plan: str
    contact_name: str | None
    contact_email: str | None


class AllowlistEntryIn(BaseModel):
    kind: AllowlistKind
    value: str
    note: str | None = None


class AllowlistEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: AllowlistKind
    value: str
    note: str | None


class WorkspaceDetail(WorkspaceOut):
    allowlist: list[AllowlistEntryOut]


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    staff: Staff = Depends(_ADMIN),
) -> Workspace:
    return ws_service.create_workspace_with_access(
        name=payload.name,
        creator_staff_id=staff.id,
        plan=payload.plan,
        slug=payload.slug,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
    )


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(staff: Staff = Depends(_STAFF)) -> list[Workspace]:
    return ws_service.list_accessible(staff)


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
def get_workspace(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> WorkspaceDetail:
    allowlist = ws_service.list_allowlist(session)
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        plan=workspace.plan,
        contact_name=workspace.contact_name,
        contact_email=workspace.contact_email,
        allowlist=[AllowlistEntryOut.model_validate(e) for e in allowlist],
    )


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    payload: WorkspaceUpdate,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> Workspace:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return workspace
    return ws_service.update_workspace(
        workspace_id=workspace.id, actor_staff_id=staff.id, changes=changes
    )


@router.get("/{workspace_id}/allowlist", response_model=list[AllowlistEntryOut])
def list_allowlist(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> list:
    return ws_service.list_allowlist(session)


@router.post(
    "/{workspace_id}/allowlist",
    response_model=AllowlistEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def add_allowlist_entry(
    payload: AllowlistEntryIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> AllowlistEntryOut:
    entry = ws_service.add_allowlist_entry(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        kind=payload.kind,
        value=payload.value,
        note=payload.note,
    )
    return AllowlistEntryOut.model_validate(entry)


@router.delete("/{workspace_id}/allowlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_allowlist_entry(
    entry_id: int,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> None:
    ws_service.remove_allowlist_entry(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        entry_id=entry_id,
    )


# Slice-0 sample route: exercises role → access → tenant session → audit write.
class WorkspaceMeResponse(BaseModel):
    workspace_id: int
    workspace_name: str
    audit_events: int


@router.get("/{workspace_id}/me", response_model=WorkspaceMeResponse)
def workspace_me(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_STAFF),
    session: Session = Depends(get_tenant_session),
) -> WorkspaceMeResponse:
    record_audit(
        session,
        workspace_id=workspace.id,
        actor_staff_id=staff.id,
        action="workspace.viewed",
        entity_type="workspace",
        entity_id=str(workspace.id),
    )
    count = session.scalar(select(func.count()).select_from(AuditLog)) or 0
    return WorkspaceMeResponse(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        audit_events=count,
    )
