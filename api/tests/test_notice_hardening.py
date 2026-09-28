"""Slice 8 send-time hard guards: allowlist re-check, and a visible delivery-failed/retry state
when the transport fails after the send is committed."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from api.app.email import get_email_backend, get_outbox
from api.app.email.backend import EmailSendError
from api.app.models.public import Workspace
from api.app.models.subjects import AllowlistKind
from api.tests.noticehelpers import confirmed_copyright_case, set_template_approval

from .reviewhelpers import add_allowlist

Auth = Callable[..., dict[str, str]]
PLATFORM = "generic_host"


def _draft_approved(client: TestClient, ws: Workspace, hdr: dict, source_url: str) -> int:
    case_id = confirmed_copyright_case(ws.schema_name, source_url=source_url)
    assert client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice", headers=hdr, json={"platform": PLATFORM}
    ).status_code == 201
    assert client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice/approve", headers=hdr,
        json={"fair_use_considered": True},
    ).status_code == 200
    return case_id


def test_send_blocked_when_target_newly_allowlisted(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = _draft_approved(client, new_workspace, hdr, "https://leak.example/p/9")

    # The domain is added to the allowlist AFTER the case opened (e.g. now an authorized reseller).
    add_allowlist(new_workspace.schema_name, AllowlistKind.domain, "leak.example")

    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "allowlist" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == 0


def test_send_blocked_when_offender_page_host_allowlisted(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    # The matched image is on a CDN host, but the offender lives on the page URL — allowlisting
    # the page host (as intake would honor) must still block the send.
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name

    from api.app.models.cases import CaseStatus

    from .casehelpers import make_case, seal_capture
    from .noticehelpers import add_copyright_rights
    from .reviewhelpers import make_subject

    subject_id = make_subject(schema, authorized=True)
    add_copyright_rights(schema, subject_id)
    case_id = make_case(
        schema, subject_id, status=CaseStatus.confirmed, claim_type="copyright",
        source_url="https://cdn.example/x.jpg", page_url="https://instagram.com/@reseller/p/1",
    )
    seal_capture(schema, case_id)
    assert client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice", headers=hdr,
        json={"platform": PLATFORM},
    ).status_code == 201
    assert client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/approve", headers=hdr,
        json={"fair_use_considered": True},
    ).status_code == 200

    # Allowlist the offender handle (only present on the page URL, not the CDN source).
    add_allowlist(schema, AllowlistKind.handle, "@reseller")

    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 422
    assert "allowlist" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == 0


def test_fair_use_tick_does_not_survive_an_edit(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    # Approve WITH the tick, edit (invalidates approval + tick), re-approve WITHOUT the tick →
    # the old tick must not leak through to send.
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(
        new_workspace.schema_name, source_url="https://leak.example/p/11"
    )
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}/notice"

    def _approve(fair_use: bool) -> int:
        return client.post(
            f"{base}/approve", headers=hdr, json={"fair_use_considered": fair_use}
        ).status_code

    assert client.post(base, headers=hdr, json={"platform": PLATFORM}).status_code == 201
    assert _approve(True) == 200
    assert client.put(base, headers=hdr, json={"subject": "s", "body": "b"}).status_code == 200
    assert _approve(False) == 200

    r = client.post(f"{base}/send", headers=hdr)
    assert r.status_code == 422
    assert "fair use" in r.json()["detail"].lower()
    assert len(get_outbox().sent) == 0


class _FailingBackend:
    name = "failing"

    def send(self, message):  # noqa: ANN001, ARG002
        raise EmailSendError("simulated transport failure")


def test_transport_failure_shows_delivery_failed_then_retry(
    client: TestClient, new_workspace: Workspace, auth_header: Auth, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_template_approval("copyright", "email", approved=True)
    get_outbox().clear()
    hdr = auth_header("admin_user")
    case_id = _draft_approved(client, new_workspace, hdr, "https://leak.example/p/10")

    # Transport fails after the send is committed.
    from api.app.services import notices as notices_svc

    monkeypatch.setattr(notices_svc, "get_email_backend", lambda: _FailingBackend())
    r = client.post(f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/send", headers=hdr)
    assert r.status_code == 502

    # The notice shows a visible delivery-failed state — NOT silently sent — but the case is Filed.
    detail = client.get(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice", headers=hdr
    ).json()
    assert detail["notice"]["status"] == "delivery_failed"
    case = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}", headers=hdr).json()
    assert case["case"]["status"] == "filed"

    # Retry with a working transport → delivered, status sent.
    monkeypatch.setattr(notices_svc, "get_email_backend", get_email_backend)
    r = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/notice/retry-send", headers=hdr
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent"
    assert len(get_outbox().sent) == 1
