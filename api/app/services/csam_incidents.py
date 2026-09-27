"""CSAM incident queue: record a match (hash/URL/time only, never bytes) and list/triage it.

Recording an incident is intentionally decoupled from the scanner (api/app/csam.py, pure) so
every storage choke point can call it. Audited so the escalation is traceable."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.models.csam import CsamIncident, CsamIncidentStatus, CsamSource


def record_incident(
    session: Session,
    *,
    workspace_id: int,
    source: CsamSource,
    sha256: str,
    url: str | None,
    subject_id: int | None = None,
    case_id: int | None = None,
    actor_staff_id: int | None = None,
) -> CsamIncident:
    """Record a CSAM match for the admin escalation queue. NEVER stores image bytes."""
    incident = CsamIncident(
        source=source,
        subject_id=subject_id,
        case_id=case_id,
        url=url,
        sha256=sha256,
        status=CsamIncidentStatus.open,
    )
    session.add(incident)
    session.flush()
    # Audit meta carries only the hash + source — never the URL content or any bytes.
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="csam.match_recorded",
        entity_type="csam_incident",
        entity_id=str(incident.id),
        meta={"source": str(source), "sha256": sha256},
    )
    return incident


def list_incidents(session: Session) -> list[CsamIncident]:
    return list(
        session.scalars(select(CsamIncident).order_by(CsamIncident.id.desc())).all()
    )


def get_incident(session: Session, incident_id: int) -> CsamIncident | None:
    return session.get(CsamIncident, incident_id)


def set_status(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    incident: CsamIncident,
    status: CsamIncidentStatus,
    note: str | None,
) -> CsamIncident:
    incident.status = status
    incident.reviewed_by_staff_id = actor_staff_id
    incident.reviewed_at = datetime.now(UTC)
    incident.note = note
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="csam.incident_triaged",
        entity_type="csam_incident",
        entity_id=str(incident.id),
        meta={"status": str(status)},
    )
    return incident
