"""Admin management of agency portal users (Slice 12). An agency user is a Staff row with
role=agency, all_workspaces=False, and exactly one StaffWorkspaceAccess grant = its workspace.
Invite-only: staff create them; Clerk provisioning happens out of band (like other staff)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess


class AgencyUserError(Exception):
    """A create/revoke precondition failed (e.g. the identity already exists)."""


def create_agency_user(
    session: Session, *, workspace_id: int, clerk_user_id: str, email: str
) -> Staff:
    """Create an agency Staff row bound to exactly one workspace. Rejects a duplicate identity."""
    existing = session.scalar(select(Staff).where(Staff.clerk_user_id == clerk_user_id))
    if existing is not None:
        raise AgencyUserError("a user with this identity already exists")
    staff = Staff(
        clerk_user_id=clerk_user_id,
        email=email,
        role=StaffRole.agency,
        all_workspaces=False,
    )
    session.add(staff)
    session.flush()
    session.add(StaffWorkspaceAccess(staff_id=staff.id, workspace_id=workspace_id))
    session.flush()
    return staff


def list_agency_users(session: Session, *, workspace_id: int) -> list[Staff]:
    stmt = (
        select(Staff)
        .join(StaffWorkspaceAccess, StaffWorkspaceAccess.staff_id == Staff.id)
        .where(
            Staff.role == StaffRole.agency,
            StaffWorkspaceAccess.workspace_id == workspace_id,
        )
        .order_by(Staff.id)
    )
    return list(session.scalars(stmt).all())


def get_agency_user(
    session: Session, *, workspace_id: int, staff_id: int
) -> Staff | None:
    """An agency Staff row that is bound to this workspace, else None."""
    stmt = (
        select(Staff)
        .join(StaffWorkspaceAccess, StaffWorkspaceAccess.staff_id == Staff.id)
        .where(
            Staff.id == staff_id,
            Staff.role == StaffRole.agency,
            StaffWorkspaceAccess.workspace_id == workspace_id,
        )
    )
    return session.scalar(stmt)


def revoke_agency_user(session: Session, *, staff: Staff) -> None:
    """Delete the agency user (cascades its access grant). Access is gone on the next request."""
    session.delete(staff)
    session.flush()
