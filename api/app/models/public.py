"""Public-schema tables: workspaces, staff, and staff→workspace access grants."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.db.base import PublicBase


class StaffRole(enum.StrEnum):
    admin = "admin"
    reviewer = "reviewer"


class Workspace(PublicBase):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="starter")
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def schema_name(self) -> str:
        # Import here to avoid a cycle at module import time.
        from api.app.db.base import schema_for_workspace

        return schema_for_workspace(self.id)


class Staff(PublicBase):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    clerk_user_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[StaffRole] = mapped_column(String(20), nullable=False)
    # Admins may be granted access to every workspace without explicit grant rows.
    all_workspaces: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    access_grants: Mapped[list[StaffWorkspaceAccess]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )


class StaffWorkspaceAccess(PublicBase):
    __tablename__ = "staff_workspace_access"
    __table_args__ = (
        UniqueConstraint("staff_id", "workspace_id", name="uq_staff_workspace"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    staff: Mapped[Staff] = relationship(back_populates="access_grants")
