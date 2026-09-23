"""Workspace-scoped sample route.

Exercises the full chain: role check → workspace-access check → tenant session → an
audit write. Later slices hang real workspace features off this pattern.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.models.audit import AuditLog
from api.app.models.public import Staff, StaffRole, Workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceMeResponse(BaseModel):
    workspace_id: int
    workspace_name: str
    audit_events: int


@router.get("/{workspace_id}/me", response_model=WorkspaceMeResponse)
def workspace_me(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(require_role(StaffRole.admin, StaffRole.reviewer)),
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
