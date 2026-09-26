"""Slice 7 API: auto-capture on confirm, evidence gate on filing, upload, verify, download,
admin-only PDF pack."""

from __future__ import annotations

import io
from collections.abc import Callable

from fastapi.testclient import TestClient
from PIL import Image

from api.app.models.public import Workspace

from .casehelpers import make_case
from .reviewhelpers import add_candidate, make_subject

Auth = Callable[..., dict[str, str]]


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 50, 50)).save(buf, "PNG")
    return buf.getvalue()


def _confirm_case(client: TestClient, ws: Workspace, hdr: dict[str, str]) -> int:
    schema = ws.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    cid = add_candidate(schema, subject_id, source_url="https://instagram.com/bad/p/1")
    r = client.post(
        f"/workspaces/{ws.id}/review/candidates/{cid}/confirm",
        headers=hdr, json={"claim_type": "likeness"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_confirm_auto_captures_and_lets_case_file(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    case_id = _confirm_case(client, new_workspace, hdr)

    captures = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}/evidence", headers=hdr)
    assert captures.status_code == 200
    rows = captures.json()
    assert len(rows) == 1 and rows[0]["kind"] == "auto" and rows[0]["status"] == "sealed"

    # A fresh sealed capture exists → filing is allowed.
    filed = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/transition",
        headers=hdr, json={"to_status": "filed"},
    )
    assert filed.status_code == 200


def test_case_without_capture_cannot_file(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    # A confirmed case with NO evidence capture (built directly, bypassing confirm's auto-capture).
    from api.app.models.cases import CaseStatus

    case_id = make_case(schema, subject_id, status=CaseStatus.confirmed, claim_type="likeness")
    r = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/transition",
        headers=hdr, json={"to_status": "filed"},
    )
    assert r.status_code == 422
    assert "evidence" in r.json()["detail"].lower()


def test_manual_upload_seals_and_downloads(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    case_id = _confirm_case(client, new_workspace, hdr)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}/evidence"

    up = client.post(
        f"{base}/upload",
        headers=hdr,
        data={"note": "screenshot taken while logged in to Instagram"},
        files={"file": ("shot.png", _png(), "image/png")},
    )
    assert up.status_code == 201, up.text
    eid = up.json()["id"]
    assert up.json()["kind"] == "manual_upload" and up.json()["status"] == "sealed"

    # Download requires a reason (custody "why").
    assert client.get(f"{base}/{eid}/artifacts/screenshot.png", headers=hdr).status_code == 422
    dl = client.get(f"{base}/{eid}/artifacts/screenshot.png?reason=review", headers=hdr)
    assert dl.status_code == 200 and dl.json()["url"]
    detail = client.get(f"{base}/{eid}", headers=hdr).json()
    assert any(c["action"] == "downloaded" for c in detail["custody"])
    assert any(c["action"] == "accessed" for c in detail["custody"])


def test_verify_endpoint(client: TestClient, new_workspace: Workspace, auth_header: Auth) -> None:
    hdr = auth_header("admin_user")
    case_id = _confirm_case(client, new_workspace, hdr)
    eid = client.get(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/evidence", headers=hdr
    ).json()[0]["id"]
    v = client.get(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/evidence/{eid}/verify?reason=audit",
        headers=hdr,
    )
    assert v.status_code == 200 and v.json()["ok"] is True


def test_pack_pdf_is_admin_only_and_needs_reason(
    client: TestClient, new_workspace: Workspace, auth_header: Auth, db
) -> None:
    hdr = auth_header("admin_user")
    case_id = _confirm_case(client, new_workspace, hdr)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}/evidence/pack.pdf"

    assert client.get(base, headers=hdr).status_code == 422  # reason required

    ok = client.get(f"{base}?reason=counsel", headers=hdr)
    assert ok.status_code == 200 and ok.content[:4] == b"%PDF"

    # A reviewer with access is denied (admin-only).
    import uuid

    from api.app.models.public import StaffRole
    from api.app.services.staff import create_staff, grant_workspace_access

    clerk = f"rev_{uuid.uuid4().hex[:8]}"
    reviewer = create_staff(clerk_user_id=clerk, email=f"{clerk}@vg.test", role=StaffRole.reviewer)
    grant_workspace_access(staff_id=reviewer.id, workspace_id=new_workspace.id)
    assert client.get(f"{base}?reason=x", headers=auth_header(clerk)).status_code == 403


def test_proof_of_removal_capture_on_removed(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    case_id = _confirm_case(client, new_workspace, hdr)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}"
    filed = client.post(f"{base}/transition", headers=hdr, json={"to_status": "filed"})
    assert filed.status_code == 200
    removed = client.post(f"{base}/transition", headers=hdr, json={"to_status": "removed"})
    assert removed.status_code == 200

    kinds = [c["kind"] for c in client.get(f"{base}/evidence", headers=hdr).json()]
    assert "proof_of_removal" in kinds
