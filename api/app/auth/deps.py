"""FastAPI auth dependencies: authentication, role checks, and workspace-access checks.

These compose as a dependency GRAPH (not a guaranteed textual order):
  * ``get_current_staff``       — valid token → an EXISTING Staff row (unknown staff → 403).
  * ``require_role(...)``        — depends on ``get_current_staff``; checks the role (else 403).
  * ``require_workspace_access`` — depends on ``get_current_staff``; checks the path's
                                   workspace grant (else 403).
  * ``get_tenant_session``      — depends on ``require_workspace_access``, so a tenant
                                   session is NEVER opened unless access has passed.
FastAPI caches ``get_current_staff`` per request, so it runs once even when several of
these are used together. The safety property (no tenant session without access) comes from
the edge ``get_tenant_session → require_workspace_access``, not from parameter ordering.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.auth.clerk import AuthError, verify_token
from api.app.config import Settings, get_settings
from api.app.db.session import public_session, tenant_session
from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess, Workspace

_bearer = HTTPBearer(auto_error=False)


def get_current_staff(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> Staff:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = verify_token(credentials.credentials, settings)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    with public_session() as session:
        staff = session.scalar(
            select(Staff).where(Staff.clerk_user_id == claims.subject)
        )
        # A valid Clerk identity is NOT access. Staff are provisioned only by an admin;
        # an unknown (or self-signed-up) user is forbidden, never auto-created.
        if staff is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="no staff account for this identity",
            )
        # Detach before the session closes; callers read scalar columns only (no lazy
        # relationship loads, which would raise DetachedInstanceError).
        session.expunge(staff)
    return staff


def require_role(*roles: StaffRole) -> Callable[..., Staff]:
    """Dependency factory: require the current staff to hold one of ``roles``."""
    allowed = set(roles)

    def _dep(staff: Staff = Depends(get_current_staff)) -> Staff:
        if staff.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient role",
            )
        return staff

    return _dep


def require_workspace_access(
    workspace_id: int = Path(..., ge=1),
    staff: Staff = Depends(get_current_staff),
) -> Workspace:
    """Verify staff may access ``workspace_id`` and return the Workspace.

    Runs before any tenant session is built. Admins with ``all_workspaces`` pass; everyone
    else needs an explicit ``StaffWorkspaceAccess`` grant.
    """
    with public_session() as session:
        workspace = session.get(Workspace, workspace_id)
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found"
            )
        if not staff.all_workspaces:
            grant = session.scalar(
                select(StaffWorkspaceAccess).where(
                    StaffWorkspaceAccess.staff_id == staff.id,
                    StaffWorkspaceAccess.workspace_id == workspace_id,
                )
            )
            if grant is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="no access to this workspace",
                )
        # Detach a lightweight copy of what callers need.
        session.expunge(workspace)
        return workspace


def get_tenant_session(
    workspace: Workspace = Depends(require_workspace_access),
) -> Iterator[Session]:
    with tenant_session(workspace.schema_name) as session:
        yield session
