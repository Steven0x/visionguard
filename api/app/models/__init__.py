"""Import all models so their metadata is registered on the bases."""

from api.app.models.audit import AuditLog
from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess, Workspace
from api.app.models.rights import (
    AgentAuthorization,
    ConsentRecord,
    ConsentType,
    RecordStatus,
    RightsRecord,
    RightsStatus,
    RightsType,
)
from api.app.models.subjects import (
    AllowlistEntry,
    AllowlistKind,
    Subject,
    SubjectStatus,
)

__all__ = [
    "AgentAuthorization",
    "AllowlistEntry",
    "AllowlistKind",
    "AuditLog",
    "ConsentRecord",
    "ConsentType",
    "RecordStatus",
    "RightsRecord",
    "RightsStatus",
    "RightsType",
    "Staff",
    "StaffRole",
    "StaffWorkspaceAccess",
    "Subject",
    "SubjectStatus",
    "Workspace",
]
