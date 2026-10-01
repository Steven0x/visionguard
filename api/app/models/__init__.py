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
from api.app.models.channels import (
    Channel,
    ChannelMethod,
    NoticeTemplate,
    TemplateApproval,
)
from api.app.models.csam import (
    CsamIncident,
    CsamIncidentStatus,
    CsamSource,
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
from api.app.models.notices import (
    FilingLog,
    FilingOutcome,
    Notice,
    NoticeStatus,
    NoticeVersion,
)
from api.app.models.outcomes import (
    NoticeOutcome,
    OutcomeKind,
    OutcomeSource,
    RecheckResult,
    UrlRecheck,
)
from api.app.models.portal import (
    PortalSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess, Workspace
from api.app.models.reports import Report
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
    "Channel",
    "ChannelMethod",
    "CsamIncident",
    "CsamIncidentStatus",
    "CsamSource",
    "CustodyAction",
    "CustodyEvent",
    "DiscoveryCandidate",
    "DiscoveryRun",
    "DiscoverySettings",
    "DismissReason",
    "EvidenceArtifact",
    "EvidenceCapture",
    "FilingLog",
    "FilingOutcome",
    "Notice",
    "NoticeOutcome",
    "NoticeStatus",
    "NoticeTemplate",
    "NoticeVersion",
    "OutcomeKind",
    "OutcomeSource",
    "PortalSubmission",
    "RecheckResult",
    "Report",
    "SubmissionKind",
    "SubmissionStatus",
    "UrlRecheck",
    "TemplateApproval",
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
