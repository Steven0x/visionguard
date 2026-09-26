"""Evidence Celery jobs: run+seal a capture (eager-safe), and retry untimestamped captures.

Like the discovery tasks, these NEVER raise: a failure is recorded on the capture row.
"""

from __future__ import annotations

from api.app.capture import capture_csam_ready, get_capture_backend
from api.app.db.base import schema_for_workspace
from api.app.db.session import tenant_session
from api.app.evidence_ts import get_timestamp
from api.app.models.cases import Case
from api.app.models.evidence import CaptureStatus, EvidenceCapture, TimestampStatus
from api.app.services import evidence as svc
from api.app.services.evidence import _MANIFEST  # manifest artifact name
from api.app.storage.evidence import get_evidence_storage
from sqlalchemy import select

from worker.celery_app import celery


@celery.task(name="worker.capture_evidence")
def capture_evidence(workspace_id: int, capture_id: int) -> str:
    schema = schema_for_workspace(workspace_id)
    with tenant_session(schema) as session:
        capture = session.get(EvidenceCapture, capture_id)
        if capture is None or capture.status != CaptureStatus.pending:
            return "skipped"
        case = session.get(Case, capture.case_id)
        if case is None:
            return "skipped"
        # CSAM gate (CLAUDE.md #7): in prod without a scanner, refuse to store anything.
        if not capture_csam_ready():
            capture.status = CaptureStatus.failed
            capture.error = "CSAM scanner not configured; capture refused (fail-closed)"
            session.flush()
            return "blocked"
        url = capture.requested_url or case.source_url
        if not url:
            capture.status = CaptureStatus.failed
            capture.error = "no URL to capture"
            session.flush()
            return "failed"
        try:
            result = get_capture_backend().capture(url)
            svc.seal_browser_capture(session, schema=schema, capture=capture, result=result)
        except Exception as exc:  # noqa: BLE001 - eager-safe; record on the row
            capture.status = CaptureStatus.failed
            capture.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            session.flush()
            return "failed"
        return "sealed"


@celery.task(name="worker.retry_untimestamped_captures")
def retry_untimestamped_captures() -> int:
    """Beat: re-attempt the TSA for sealed-but-untimestamped captures."""
    from api.app.db.session import public_session
    from api.app.models.public import Workspace

    with public_session() as session:
        workspace_ids = list(session.scalars(select(Workspace.id)).all())

    retried = 0
    storage = get_evidence_storage()
    for workspace_id in workspace_ids:
        schema = schema_for_workspace(workspace_id)
        with tenant_session(schema) as session:
            captures = list(
                session.scalars(
                    select(EvidenceCapture).where(
                        EvidenceCapture.status == CaptureStatus.sealed,
                        EvidenceCapture.timestamp_status == TimestampStatus.untimestamped,
                    )
                ).all()
            )
            for capture in captures:
                artifacts = svc.list_artifacts(session, capture.id)
                # Idempotency: never re-seal a .tsr that already exists (write-once → would raise).
                if any(a.name == "manifest.tsr" for a in artifacts):
                    continue
                artifact = next((a for a in artifacts if a.name == _MANIFEST), None)
                if artifact is None:
                    continue
                try:
                    manifest_bytes = storage.get_object(artifact.object_key)
                    ts = get_timestamp(manifest_bytes)
                    if ts.ok and ts.token is not None:
                        from api.app.models.evidence import EvidenceArtifact

                        tsr_key = svc._evidence_key(schema, capture.id, "manifest.tsr")
                        storage.seal_object(tsr_key, ts.token, "application/timestamp-reply")
                        session.add(
                            EvidenceArtifact(
                                capture_id=capture.id, name="manifest.tsr", object_key=tsr_key,
                                sha256=svc._sha256(ts.token),
                                content_type="application/timestamp-reply",
                                size_bytes=len(ts.token),
                            )
                        )
                        capture.timestamp_status = TimestampStatus.ok
                        capture.tsa_url = ts.tsa_url
                        capture.tsa_time = ts.tsa_time
                        retried += 1
                except Exception:  # noqa: BLE001, S112 - one bad capture must not halt the sweep
                    continue
    return retried
