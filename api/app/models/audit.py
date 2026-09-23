"""Tenant-schema audit log. One row per meaningful action; append-only.

Lives in each workspace's schema (symbolic ``tenant`` token), so it is tenant-isolated by
construction. There is no update/delete path in code, and the tenant migration additionally
REVOKEs UPDATE/DELETE on the table (see migrations/versions/0002_tenant.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db.base import TenantBase


class AuditLog(TenantBase):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Staff live in the public schema; store the id as a plain int (no cross-schema FK).
    actor_staff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
