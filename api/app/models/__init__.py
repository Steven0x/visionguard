"""Import all models so their metadata is registered on the bases."""

from api.app.models.audit import AuditLog
from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess, Workspace
from api.app.models.subjects import (
    AllowlistEntry,
    AllowlistKind,
    Subject,
    SubjectStatus,
)

__all__ = [
    "AllowlistEntry",
    "AllowlistKind",
    "AuditLog",
    "Staff",
    "StaffRole",
    "StaffWorkspaceAccess",
    "Subject",
    "SubjectStatus",
    "Workspace",
]
