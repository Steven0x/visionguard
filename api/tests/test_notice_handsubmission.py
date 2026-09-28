"""Web-form/portal path: copy-ready packet, then a hand-submission that CSAM-scans + seals the
confirmation screenshot, records the ticket, and files the case. A CSAM match fails closed."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app.config import get_settings
from api.app.models.cases import CaseStatus
from api.app.models.public import Workspace
from api.tests.noticehelpers import add_copyright_rights, set_template_approval

from .casehelpers import make_case, seal_capture
from .reviewhelpers import make_subject

Auth = Callable[..., dict[str, str]]
# Copyright is the only claim whose template can be counsel-approved in Phase 1; instagram's
# copyright channel is a web_form, so it exercises the packet + hand-submission path.
PLATFORM = "instagram"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _copyright_web_case(schema: str) -> int:
    subject_id = make_subject(schema, authorized=True)
    add_copyright_rights(schema, subject_id)
    case_id = make_case(
        schema, subject_id, status=CaseStatus.confirmed, claim_type="copyright",
        source_url="https://instagram.com/fake/p/1",
    )
    seal_capture(schema, case_id)
    return case_id


def _draft_and_approve(client: TestClient, ws: Workspace, hdr: dict, case_id: int) -> None:
    r = client.post(f"/workspaces/{ws.id}/cases/{case_id}/notice", headers=hdr,
                    json={"platform": PLATFORM})
    assert r.status_code == 201, r.text
    r = client.post(f"/workspaces/{ws.id}/cases/{case_id}/notice/approve", headers=hdr,
                    json={"fair_use_considered": True})
    assert r.status_code == 200, r.text


def test_packet_then_hand_submission_files_case(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "web_form", approved=True)
    hdr = auth_header("admin_user")
    case_id = _copyright_web_case(new_workspace.schema_name)
    _draft_and_approve(client, new_workspace, hdr, case_id)

    packet = client.get(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/packet", headers=hdr
    )
    assert packet.status_code == 200, packet.text
    assert packet.json()["destination"].startswith("http")

    r = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/hand-submission",
        headers=hdr, data={"ticket_number": "IG-12345"},
        files={"file": ("proof.png", _png(), "image/png")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "sent"

    case = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}", headers=hdr).json()
    assert case["case"]["status"] == "filed"

    log = client.get(f"/workspaces/{new_workspace.id}/filing-log", headers=hdr).json()
    assert any(row["outcome"] == "submitted_by_hand" and row["ticket_number"] == "IG-12345"
               for row in log)

    caps = client.get(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/evidence", headers=hdr
    ).json()
    assert any(c["kind"] == "manual_upload" and c["status"] == "sealed" for c in caps)


def test_hand_submission_csam_match_fails_closed(
    client: TestClient, new_workspace: Workspace, auth_header: Auth, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_template_approval("copyright", "web_form", approved=True)
    hdr = auth_header("admin_user")
    case_id = _copyright_web_case(new_workspace.schema_name)
    _draft_and_approve(client, new_workspace, hdr, case_id)

    monkeypatch.setattr(get_settings(), "csam_fake_result", "match")
    r = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/hand-submission",
        headers=hdr, data={"ticket_number": "IG-9"},
        files={"file": ("proof.png", _png(), "image/png")},
    )
    assert r.status_code == 422
    assert "csam" in r.json()["detail"].lower()

    # Case stays Confirmed; nothing filed.
    case = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}", headers=hdr).json()
    assert case["case"]["status"] == "confirmed"
