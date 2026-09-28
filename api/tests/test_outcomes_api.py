"""Outcomes API (Slice 9): record an outcome over HTTP, the follow-up list, and the metrics
endpoint."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.app.models.cases import CaseStatus
from api.app.models.public import Workspace
from api.tests.casehelpers import make_case, past_due
from api.tests.noticehelpers import confirmed_copyright_case, set_template_approval
from api.tests.reviewhelpers import make_subject

Auth = Callable[..., dict[str, str]]
PLATFORM = "generic_host"


def _file_case(client: TestClient, ws: Workspace, hdr: dict, case_id: int) -> None:
    assert client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice", headers=hdr, json={"platform": PLATFORM}
    ).status_code == 201
    assert client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice/approve", headers=hdr,
        json={"fair_use_considered": True},
    ).status_code == 200
    assert client.post(
        f"/workspaces/{ws.id}/cases/{case_id}/notice/send", headers=hdr
    ).status_code == 200


def test_record_removed_outcome_via_api(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _file_case(client, new_workspace, hdr, case_id)

    r = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/outcomes", headers=hdr,
        json={"outcome": "removed"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["effective_outcome"] == "removed"

    case = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}", headers=hdr).json()
    assert case["case"]["status"] == "removed"


def test_supersede_outcome_via_api(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _file_case(client, new_workspace, hdr, case_id)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}/outcomes"

    r1 = client.post(base, headers=hdr, json={"outcome": "no_response"})
    assert r1.status_code == 201, r1.text
    prior_id = r1.json()["outcomes"][-1]["id"]

    # Correct it (append-only) — the case is still Filed after no_response.
    r2 = client.post(
        base, headers=hdr,
        json={"outcome": "rejected", "supersedes_id": prior_id, "note": "actually refused"},
    )
    assert r2.status_code == 201, r2.text
    detail = r2.json()
    assert detail["effective_outcome"] == "rejected"
    assert len(detail["outcomes"]) == 2  # append-only: both rows survive


def test_outcome_on_non_filed_case_is_rejected(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    subject = make_subject(new_workspace.schema_name, authorized=True)
    # A confirmed (not filed) case with no notice.
    case_id = make_case(new_workspace.schema_name, subject, status=CaseStatus.confirmed)
    r = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/outcomes", headers=hdr,
        json={"outcome": "removed"},
    )
    assert r.status_code == 404  # no filed notice for this case


def test_follow_ups_lists_overdue_filed_cases(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    subject = make_subject(new_workspace.schema_name, authorized=True)
    overdue = make_case(
        new_workspace.schema_name, subject, status=CaseStatus.filed, due_at=past_due(),
    )
    make_case(new_workspace.schema_name, subject, status=CaseStatus.confirmed)  # not filed

    r = client.get(f"/workspaces/{new_workspace.id}/follow-ups", headers=hdr)
    assert r.status_code == 200
    rows = r.json()
    assert any(f["case_id"] == overdue and f["reason"] == "overdue" for f in rows)


def test_metrics_endpoint_returns_rows(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    set_template_approval("copyright", "email", approved=True)
    hdr = auth_header("admin_user")
    case_id = confirmed_copyright_case(new_workspace.schema_name)
    _file_case(client, new_workspace, hdr, case_id)
    client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/outcomes", headers=hdr,
        json={"outcome": "removed"},
    )

    r = client.get(f"/workspaces/{new_workspace.id}/metrics/removals", headers=hdr)
    assert r.status_code == 200
    rows = {(m["platform"], m["claim_type"]): m for m in r.json()}
    assert (PLATFORM, "copyright") in rows
    assert rows[(PLATFORM, "copyright")]["removed"] == 1
