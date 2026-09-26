"""Slice 7 service/worker: capture+seal, verify (+tamper), CSAM fail-closed, manual upload,
freshness gate, PDF pack."""

from __future__ import annotations

import io

from PIL import Image

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.cases import Case
from api.app.models.evidence import CaptureKind, CaptureStatus, TimestampStatus
from api.app.models.public import Workspace
from api.app.services import evidence as ev
from api.app.storage.evidence import get_evidence_storage

from .casehelpers import make_case, seal_capture
from .reviewhelpers import make_subject

_SEALED_ARTIFACTS = {"screenshot.png", "page.html", "page.mhtml", "meta.json", "manifest.json"}


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _open_case(schema: str) -> int:
    subject_id = make_subject(schema, enforcement_consent=True)
    return make_case(schema, subject_id, source_url="https://x.example/p")


def test_capture_seals_artifacts_manifest_and_timestamp(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    case_id = _open_case(schema)
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        capture = ev.trigger_capture(
            session, workspace_id=new_workspace.id, case=case,
            kind=CaptureKind.auto, actor_staff_id=None,
        )
        capture_id = capture.id

    with tenant_session(schema) as session:
        sealed = ev.get_capture(session, capture_id)
        assert sealed is not None and sealed.status == CaptureStatus.sealed
        assert sealed.timestamp_status == TimestampStatus.ok  # fake TSA answers
        names = {a.name for a in ev.list_artifacts(session, capture_id)}
        assert _SEALED_ARTIFACTS <= names and "manifest.tsr" in names
        assert any(c.action == "captured" for c in ev.list_custody(session, case_id))


def test_verify_passes_then_fails_on_tamper(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    case_id = _open_case(schema)
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        capture_id = ev.trigger_capture(
            session, workspace_id=new_workspace.id, case=case,
            kind=CaptureKind.auto, actor_staff_id=None,
        ).id

    with tenant_session(schema) as session:
        capture = ev.get_capture(session, capture_id)
        assert capture is not None
        clean = ev.verify_capture(session, schema=schema, capture=capture, actor_staff_id=None,
                                  reason="check")
        assert clean.ok and clean.manifest_ok and clean.timestamp_ok

    # Tamper with THIS capture's stored screenshot (bypassing write-once via store internals).
    store = get_evidence_storage()
    with tenant_session(schema) as session:
        shot = next(
            a for a in ev.list_artifacts(session, capture_id) if a.name == "screenshot.png"
        )
        store._objects[shot.object_key] = b"tampered"  # type: ignore[attr-defined]
        capture = ev.get_capture(session, capture_id)
        assert capture is not None
        result = ev.verify_capture(session, schema=schema, capture=capture, actor_staff_id=None,
                                   reason="recheck")
        assert result.ok is False and result.files["screenshot.png"] is False


def test_csam_gate_fails_closed_without_scanner(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    case_id = _open_case(schema)
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        capture = ev.create_pending_capture(
            session, case=case, kind=CaptureKind.auto,
            requested_url="https://x.example/p", captured_by_staff_id=None,
        )
        session.commit()
        capture_id = capture.id

    from worker.evidence import capture_evidence

    settings = get_settings()
    settings.capture_backend = "playwright"  # real backend + no scanner → must refuse
    try:
        assert capture_evidence(new_workspace.id, capture_id) == "blocked"
    finally:
        settings.capture_backend = "fake"

    with tenant_session(schema) as session:
        blocked = ev.get_capture(session, capture_id)
        assert blocked is not None and blocked.status == CaptureStatus.failed
        assert ev.list_artifacts(session, capture_id) == []  # nothing stored


def test_manual_upload_is_sealed(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    case_id = _open_case(schema)
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        capture = ev.create_pending_capture(
            session, case=case, kind=CaptureKind.manual_upload,
            requested_url=case.source_url, captured_by_staff_id=None,
        )
        ev.seal_manual_upload(session, schema=schema, capture=capture,
                              screenshot_png=_png(), attestation="I saw this while logged in")
        capture_id = capture.id
        assert capture.status == CaptureStatus.sealed
        names = {a.name for a in ev.list_artifacts(session, capture_id)}
        assert {"screenshot.png", "meta.json", "manifest.json"} <= names


def test_freshness_gate(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    case_id = _open_case(schema)
    with tenant_session(schema) as session:
        assert ev.has_fresh_sealed_capture(session, case_id) is False
    seal_capture(schema, case_id)
    with tenant_session(schema) as session:
        assert ev.has_fresh_sealed_capture(session, case_id) is True


def test_pdf_pack_renders(new_workspace: Workspace, db) -> None:
    schema = new_workspace.schema_name
    case_id = _open_case(schema)
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        ev.trigger_capture(session, workspace_id=new_workspace.id, case=case,
                           kind=CaptureKind.auto, actor_staff_id=None)
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        pdf = ev.build_pack_pdf(session, schema=schema, case=case,
                                actor_staff_id=db.admin_staff_id, reason="counsel review",
                                include_sensitive=False)
        assert pdf[:4] == b"%PDF"
        assert any(c.action == "exported" for c in ev.list_custody(session, case_id))
