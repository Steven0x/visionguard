"""The send gate (Slice 8): nothing sends on an unapproved template; a confirmed copyright case
on an email channel sends with one approval, seals the notice, logs the filing, and files the
case; send-time re-checks fail closed."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import update

from api.app.db.session import tenant_session
from api.app.email import get_outbox
from api.app.models.public import Workspace
from api.app.models.rights import AgentAuthorization, RecordStatus
from api.tests.noticehelpers import confirmed_copyright_case, set_template_approval

Auth = Callable[..., dict[str, str]]
PLATFORM = "generic_host"


def _draft(client: TestClient, ws: Workspace, hdr: dict, case_id: int) -> None:
    r = client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice", headers=hdr,
        json={"platform": PLATFORM},
    )
    assert r.status_code == 201, r.text


def _approve(
    client: TestClient, ws: Workspace, hdr: dict, case_id: int, *, fair_use: bool = True
) -> None:
    r = client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice/approve", headers=hdr,
        json={"fair_use_considered": fair_use},
    )
    assert r.status_code == 200, r.text


def test_unapproved_template_cannot_send(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=False)
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _draft(client, new_workspace, hdr, case_id)
    _approve(client, new_workspace, hdr, case_id)

    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "counsel" in r.json()["detail"].lower()


def test_approved_copyright_email_sends_seals_and_files(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _draft(client, new_workspace, hdr, case_id)
    _approve(client, new_workspace, hdr, case_id)

    before = len(get_outbox().sent)
    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 200, r.text
    notice = r.json()
    assert notice["status"] == "sent"
    assert notice["sealed_capture_id"] is not None

    # Exactly one message went to the outbox (never a real send).
    assert len(get_outbox().sent) == before + 1
    msg = get_outbox().sent[-1]
    assert msg.to and "@" in msg.to[0]

    # The case moved to Filed.
    case = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}", headers=hdr).json()
    assert case["case"]["status"] == "filed"

    # A sealed notice capture exists.
    caps = client.get(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/evidence", headers=hdr
    ).json()
    notice_caps = [c for c in caps if c["kind"] == "notice"]
    assert len(notice_caps) == 1 and notice_caps[0]["status"] == "sealed"

    # A filing-log row was written.
    log = client.get(f"/workspaces/{new_workspace.id}/filing-log", headers=hdr).json()
    assert any(row["outcome"] == "sent" and row["platform"] == PLATFORM for row in log)


def test_send_fails_closed_when_authorization_lapses(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _draft(client, new_workspace, hdr, case_id)
    _approve(client, new_workspace, hdr, case_id)

    # Authorization revoked AFTER drafting/approval — send must re-check and refuse.
    with tenant_session(new_workspace.schema_name) as s:
        s.execute(update(AgentAuthorization).values(status=RecordStatus.revoked))

    before = len(get_outbox().sent)
    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "authorization" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == before  # nothing sent


def test_send_fails_closed_without_fresh_evidence(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    # Build a confirmed copyright case WITHOUT sealing a capture.
    from api.app.models.cases import CaseStatus

    from .casehelpers import make_case
    from .noticehelpers import add_copyright_rights
    from .reviewhelpers import make_subject

    schema = new_workspace.schema_name
    subject_id = make_subject(schema, authorized=True)
    add_copyright_rights(schema, subject_id)
    case_id = make_case(
        schema, subject_id, status=CaseStatus.confirmed, claim_type="copyright",
        source_url="https://leak.example/p/2",
    )
    _draft(client, new_workspace, hdr, case_id)
    _approve(client, new_workspace, hdr, case_id)

    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "evidence" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == 0


def test_edit_after_approval_requires_reapproval(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    # A reviewer must not be able to approve one version and then send an edited, unreviewed one.
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _draft(client, new_workspace, hdr, case_id)
    _approve(client, new_workspace, hdr, case_id)

    # Edit AFTER approval → bumps the version, stale approval.
    r = client.put(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice", headers=hdr,
        json={"subject": "Edited subject", "body": "ATTACKER-CONTROLLED UNREVIEWED BODY"},
    )
    assert r.status_code == 200, r.text

    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "re-approve" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == 0

    # Re-approving the current version unblocks the send.
    _approve(client, new_workspace, hdr, case_id)
    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 200, r.text
    assert len(get_outbox().sent) == 1
    assert "ATTACKER-CONTROLLED" in get_outbox().sent[-1].body


def test_copyright_send_requires_fair_use_tick(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _draft(client, new_workspace, hdr, case_id)
    # Approved WITHOUT ticking fair use → send blocked.
    _approve(client, new_workspace, hdr, case_id, fair_use=False)
    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "fair use" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == 0

    # Re-approve WITH the tick → sends.
    _approve(client, new_workspace, hdr, case_id, fair_use=True)
    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 200, r.text
    assert len(get_outbox().sent) == 1


def test_send_requires_human_approval(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _draft(client, new_workspace, hdr, case_id)
    # NOT approved by a human → send refused.
    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "approved" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == 0
