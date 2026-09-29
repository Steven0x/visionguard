"""Re-upload watch Celery beat jobs (Slice 9): re-check open URLs and run the monitoring tail.

Like the other beat tasks these NEVER raise: a bad case/workspace is skipped, not fatal. The
re-check only *proposes* removals/reappearances (a human confirms); the monitoring lifecycle
transitions are system housekeeping (actor None, audited), never outbound.
"""

from __future__ import annotations

from datetime import UTC, datetime

from api.app.audit.service import record_audit
from api.app.db.base import schema_for_workspace
from api.app.db.session import public_session, tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.evidence import CaptureKind, CaptureStatus, EvidenceCapture
from api.app.models.public import Workspace
from api.app.services import cases as cases_svc
from api.app.services import recheck as recheck_svc
from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.celery_app import celery
from worker.locks import single_run


def _workspace_ids() -> list[int]:
    with public_session() as session:
        return list(session.scalars(select(Workspace.id)).all())


@celery.task(name="worker.recheck_open_urls")
@single_run("recheck-open-urls")
def recheck_open_urls() -> int:
    """Beat: probe every open filed/monitoring case's URL and record + evaluate the result."""
    checked = 0
    for workspace_id in _workspace_ids():
        schema = schema_for_workspace(workspace_id)
        with tenant_session(schema) as session:
            cases = list(
                session.scalars(
                    select(Case).where(
                        Case.status.in_([CaseStatus.filed, CaseStatus.monitoring])
                    )
                ).all()
            )
            for case in cases:
                try:
                    row = recheck_svc.run_recheck(
                        session, workspace_id=workspace_id, case=case
                    )
                except Exception:  # noqa: BLE001, S112 - one bad case must not halt the sweep
                    continue
                if row is not None:
                    checked += 1
    return checked


def _proof_of_removal_sealed(session: Session, case_id: int) -> bool:
    return (
        session.scalar(
            select(EvidenceCapture.id).where(
                EvidenceCapture.case_id == case_id,
                EvidenceCapture.kind == CaptureKind.proof_of_removal,
                EvidenceCapture.status == CaptureStatus.sealed,
            ).limit(1)
        )
        is not None
    )


@celery.task(name="worker.run_monitoring_lifecycle")
@single_run("run-monitoring-lifecycle")
def run_monitoring_lifecycle() -> dict[str, int]:
    """Beat: advance ``removed → monitoring`` (once the proof capture has sealed) and
    ``monitoring → closed`` (once the watch window has elapsed with no reappearance pending)."""
    advanced = 0
    closed = 0
    now = datetime.now(UTC)
    for workspace_id in _workspace_ids():
        schema = schema_for_workspace(workspace_id)
        with tenant_session(schema) as session:
            for case in session.scalars(
                select(Case).where(Case.status == CaseStatus.removed)
            ).all():
                if not _proof_of_removal_sealed(session, case.id):
                    continue  # wait for the sealed removal proof before starting the watch
                try:
                    cases_svc.transition(
                        session, workspace_id=workspace_id, actor_staff_id=None, case=case,
                        to_status=CaseStatus.monitoring, reason="auto_monitoring",
                    )
                    advanced += 1
                except (cases_svc.IllegalTransition, cases_svc.CaseConflict):
                    continue
            for case in session.scalars(
                select(Case).where(Case.status == CaseStatus.monitoring)
            ).all():
                # Never auto-close a removal the rechecks couldn't verify (all `live` since the
                # removal — a soft-404 platform). Flag it for a human to confirm-close or reopen.
                if recheck_svc.removal_unverified(session, case):
                    if case.removal_unverified_at is None:
                        case.removal_unverified_at = now
                        session.flush()
                        record_audit(
                            session, workspace_id=workspace_id, actor_staff_id=None,
                            action="case.removal_unverified", entity_type="case",
                            entity_id=str(case.id), meta={},
                        )
                    continue
                if case.removal_unverified_at is not None:
                    case.removal_unverified_at = None  # a gone recheck cleared the doubt
                    session.flush()
                    record_audit(
                        session, workspace_id=workspace_id, actor_staff_id=None,
                        action="case.removal_verified", entity_type="case",
                        entity_id=str(case.id), meta={},
                    )
                if case.reappearance_proposed_at is not None:
                    continue  # a pending reappearance must be resolved by a human first
                if case.due_at is None or case.due_at >= now:
                    continue  # watch window not yet elapsed
                try:
                    cases_svc.transition(
                        session, workspace_id=workspace_id, actor_staff_id=None, case=case,
                        to_status=CaseStatus.closed, reason="monitoring_window_elapsed",
                    )
                    closed += 1
                except (cases_svc.IllegalTransition, cases_svc.CaseConflict):
                    continue
    return {"advanced": advanced, "closed": closed}
