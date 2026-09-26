"""Import all models so their metadata is registered on the bases."""

from api.app.models.assets import Asset, AssetStatus, SubjectKeyword
from api.app.models.audit import AuditLog
from api.app.models.cases import (
    Case,
    CaseEvent,
    CaseEventKind,
    CaseNote,
    CaseStatus,
)
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    DiscoverySettings,
    ReviewStatus,
    RunKind,
    RunStatus,
    ScanFrequency,
)
from api.app.models.evidence import (
    CaptureKind,
    CaptureStatus,
    CustodyAction,
    CustodyEvent,
    EvidenceArtifact,
    EvidenceCapture,
    TimestampStatus,
)
from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess, Workspace
from api.app.models.review import (
    DismissReason,
    ReviewDecision,
    ReviewDecisionKind,
)
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
    "Asset",
    "AssetStatus",
    "AuditLog",
    "CandidateKind",
    "Case",
    "CaseEvent",
    "CaseEventKind",
    "CaseNote",
    "CaseStatus",
    "CaptureKind",
    "CaptureStatus",
    "CustodyAction",
    "CustodyEvent",
    "DiscoveryCandidate",
    "DiscoveryRun",
    "DiscoverySettings",
    "DismissReason",
    "EvidenceArtifact",
    "EvidenceCapture",
    "TimestampStatus",
    "ReviewDecision",
    "ReviewDecisionKind",
    "ReviewStatus",
    "RunKind",
    "RunStatus",
    "ScanFrequency",
    "SubjectKeyword",
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
