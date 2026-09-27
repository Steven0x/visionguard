"""Admin-only CSAM escalation queue. Rows hold only hash/URL/time (never image bytes) and
feed the NCMEC report path (CLAUDE.md #7)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.app.auth.deps import get_tenant_session, require_role, require_workspace_access
from api.app.models.csam import CsamIncident, CsamIncidentStatus
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import csam_incidents as svc

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["csam"])

_ADMIN = require_role(StaffRole.admin)  # escalation queue is admin-only


class IncidentOut(BaseModel):
    id: int
    source: str
    subject_id: int | None
    case_id: int | None
    url: str | None
    sha256: str
    status: str
    detected_at: datetime
    reviewed_by_staff_id: int | None
    note: str | None

    @classmethod
    def of(cls, i: CsamIncident) -> IncidentOut:
        return cls(
            id=i.id, source=str(i.source), subject_id=i.subject_id, case_id=i.case_id,
            url=i.url, sha256=i.sha256, status=str(i.status), detected_at=i.detected_at,
            reviewed_by_staff_id=i.reviewed_by_staff_id, note=i.note,
        )


class TriageIn(BaseModel):
    status: CsamIncidentStatus
    note: str | None = Field(default=None, max_length=2000)


@router.get("/csam-incidents", response_model=list[IncidentOut])
def list_incidents(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> list[IncidentOut]:
    return [IncidentOut.of(i) for i in svc.list_incidents(session)]


@router.post("/csam-incidents/{incident_id}/status", response_model=IncidentOut)
def triage_incident(
    incident_id: int,
    payload: TriageIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
    session: Session = Depends(get_tenant_session),
) -> IncidentOut:
    incident = svc.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    updated = svc.set_status(
        session, workspace_id=workspace.id, actor_staff_id=staff.id,
        incident=incident, status=payload.status, note=payload.note,
    )
    return IncidentOut.of(updated)
