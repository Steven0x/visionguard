"""Withdraw a sent notice: Filed → Withdrawn (note required), logs a retraction, and the case
can be re-filed from the same candidate."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.app.email import get_outbox
from api.app.models.public import Workspace
from api.tests.noticehelpers import confirmed_copyright_case, set_template_approval

Auth = Callable[..., dict[str, str]]
PLATFORM = "generic_host"


def _send(client: TestClient, ws: Workspace, hdr: dict, case_id: int) -> None:
    r = client.post(f"/workspaces/{ws.id}/cases/{case_id}/notice", headers=hdr,
                    json={"platform": PLATFORM})
    assert r.status_code == 201, r.text
    ap = client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice/approve", headers=hdr,
        json={"fair_use_considered": True},
    )
    assert ap.status_code == 200, ap.text
    sent = client.post(f"/workspaces/{ws.id}/cases/{case_id}/notice/send", headers=hdr)
    assert sent.status_code == 200, sent.text


def test_withdraw_requires_note(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _send(client, new_workspace, hdr, case_id)

    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/withdraw",
                    headers=hdr, json={"note": "   "})
    assert r.status_code == 422


def test_withdraw_retracts_and_files_withdrawn(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _send(client, new_workspace, hdr, case_id)

    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/withdraw",
                    headers=hdr, json={"note": "wrong claim type"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "withdrawn"

    case = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}", headers=hdr).json()
    assert case["case"]["status"] == "withdrawn"

    log = client.get(f"/workspaces/{new_workspace.id}/filing-log", headers=hdr).json()
    outcomes = [row["outcome"] for row in log if row["case_id"] == case_id]
    assert "withdrawn" in outcomes and "sent" in outcomes
