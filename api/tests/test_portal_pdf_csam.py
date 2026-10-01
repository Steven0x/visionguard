"""Outsider PDF uploads (Slice 12, addition #1): embedded images are CSAM-scanned and the upload
fails closed on a match — an incident is recorded, no bytes are stored, the submission is rejected.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.config import get_settings
from api.app.db.session import tenant_session
from api.app.models.csam import CsamIncident
from api.app.models.portal import PortalSubmission
from api.app.models.public import Workspace
from api.tests.portalhelpers import make_agency_user, pdf_text_only, pdf_with_image
from api.tests.reviewhelpers import make_subject


def _agency(client: TestClient, ws: Workspace, auth_header):
    make_agency_user(
        clerk_user_id=f"agency_pdf_{ws.id}", email="pdf@agency.test", workspace_id=ws.id
    )
    return auth_header(f"agency_pdf_{ws.id}")


def test_pdf_with_matching_image_is_blocked_and_recorded(
    client: TestClient, new_workspace: Workspace, auth_header, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema)
    hdr = _agency(client, new_workspace, auth_header)
    monkeypatch.setattr(get_settings(), "csam_fake_result", "match")

    resp = client.post(
        "/portal/needs/answer",
        headers=hdr,
        data={"subject_id": str(sid), "need_type": "ownership_rights"},
        files={"file": ("doc.pdf", pdf_with_image(), "application/pdf")},
    )
    assert resp.status_code == 422
    with tenant_session(schema) as session:
        incident = session.scalar(select(CsamIncident))
        assert incident is not None and incident.source == "portal_upload"
        # Nothing stored: no submission row.
        assert session.scalar(select(PortalSubmission)) is None


def test_clean_pdf_is_accepted_and_queued(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    schema = new_workspace.schema_name
    sid = make_subject(schema)
    hdr = _agency(client, new_workspace, auth_header)
    resp = client.post(
        "/portal/needs/answer",
        headers=hdr,
        data={"subject_id": str(sid), "need_type": "ownership_rights", "body": "see attached"},
        files={"file": ("doc.pdf", pdf_text_only(), "application/pdf")},
    )
    assert resp.status_code == 201
    with tenant_session(schema) as session:
        sub = session.scalar(select(PortalSubmission))
        assert sub is not None and sub.file_key is not None
        # Stored under the quarantine prefix — never an inline-rendered path.
        assert "/quarantine/needs_response/" in sub.file_key


def test_non_pdf_rejected(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    sid = make_subject(new_workspace.schema_name)
    hdr = _agency(client, new_workspace, auth_header)
    resp = client.post(
        "/portal/needs/answer",
        headers=hdr,
        data={"subject_id": str(sid), "need_type": "ownership_rights"},
        files={"file": ("x.png", b"\x89PNG\r\n\x1a\n not really", "application/pdf")},
    )
    assert resp.status_code == 422
