"""CSAM gate (CLAUDE.md #7): nothing is stored/sealed without a `clean` scan; a match records a
minimized incident and stores no bytes; the fake scanner is refused outside dev/test."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import func, select

from api.app.config import Settings, get_settings
from api.app.db.session import tenant_session
from api.app.models.cases import Case
from api.app.models.csam import CsamIncident
from api.app.models.evidence import CaptureKind, CaptureStatus, EvidenceArtifact, EvidenceCapture
from api.app.models.public import Workspace
from api.app.services import evidence as ev
from api.app.services.assets import CsamBlocked, create_asset

from .casehelpers import make_case
from .reviewhelpers import make_subject


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()

Auth = Callable[..., dict[str, str]]


def test_fake_scanner_refused_outside_dev_test() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(app_env="staging", auth_test_mode=False, csam_scanner_backend="fake")
    assert "CSAM_SCANNER_BACKEND=fake" in str(exc.value)


def _open_case(schema: str) -> int:
    subject_id = make_subject(schema, enforcement_consent=True)
    return make_case(schema, subject_id, source_url="https://x.example/p")


def test_capture_match_stores_nothing_and_records_incident(
    new_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "csam_fake_result", "match")
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
        capture = session.get(EvidenceCapture, capture_id)
        assert capture is not None and capture.status == CaptureStatus.blocked
        # No bytes sealed.
        artifacts = session.scalar(
            select(func.count()).select_from(EvidenceArtifact).where(
                EvidenceArtifact.capture_id == capture_id
            )
        )
        assert artifacts == 0
        # A minimized incident exists (hash/url/time only — no image column exists at all).
        incident = session.scalar(select(CsamIncident))
        assert incident is not None
        assert incident.source == "capture" and len(incident.sha256) == 64


def test_asset_upload_match_stores_nothing_and_records_incident(
    new_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "csam_fake_result", "match")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema)
    with tenant_session(schema) as session:
        with pytest.raises(CsamBlocked):
            create_asset(
                session, workspace_id=new_workspace.id, schema=schema, actor_staff_id=None,
                subject_id=subject_id, data=_png(), content_type="image/png", file_name="a.png",
            )
        incident = session.scalar(select(CsamIncident))
        assert incident is not None and incident.source == "asset_upload"


def test_none_scanner_blocks_capture(
    new_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "csam_scanner_backend", "none")
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
        capture = session.get(EvidenceCapture, capture_id)
        assert capture is not None and capture.status == CaptureStatus.blocked
        assert ev.list_artifacts(session, capture_id) == []
