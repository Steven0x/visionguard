"""Staff administration: create staff and grant workspace access. Admin-only in the app.

The ``seed-first-admin`` CLI is the one bootstrap path that can create a staff row without
an existing admin (used once, to create the very first admin).
"""

from __future__ import annotations

from sqlalchemy import select

from api.app.db.session import public_session
from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess


def create_staff(
    *,
    clerk_user_id: str,
    email: str,
    role: StaffRole,
    all_workspaces: bool = False,
) -> Staff:
    with public_session() as session:
        staff = Staff(
            clerk_user_id=clerk_user_id,
            email=email,
            role=role,
            all_workspaces=all_workspaces,
        )
        session.add(staff)
        session.flush()
        session.refresh(staff)
        session.expunge(staff)
        return staff


def grant_workspace_access(*, staff_id: int, workspace_id: int) -> None:
    with public_session() as session:
        exists = session.scalar(
            select(StaffWorkspaceAccess).where(
                StaffWorkspaceAccess.staff_id == staff_id,
                StaffWorkspaceAccess.workspace_id == workspace_id,
            )
        )
        if exists is None:
            session.add(
                StaffWorkspaceAccess(staff_id=staff_id, workspace_id=workspace_id)
            )


def seed_first_admin(*, clerk_user_id: str, email: str) -> Staff:
    """Create the first admin (with all-workspaces access). Refuses if any staff exist."""
    with public_session() as session:
        if session.scalar(select(Staff.id).limit(1)) is not None:
            raise RuntimeError(
                "staff already exist; create further staff through an admin, not seed"
            )
    return create_staff(
        clerk_user_id=clerk_user_id,
        email=email,
        role=StaffRole.admin,
        all_workspaces=True,
    )
