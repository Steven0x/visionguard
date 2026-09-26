"""Slice 6 API: list/filter, detail + timeline, transitions (legal only), claim, notes, assign."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from api.app.models.cases import CaseStatus
from api.app.models.public import Workspace

from .casehelpers import make_case, past_due
from .reviewhelpers import add_candidate, make_subject

Auth = Callable[..., dict[str, str]]


def _open_case(client: TestClient, ws: Workspace, hdr: dict[str, str]) -> tuple[int, int]:
    """Confirm a candidate through the review flow → returns (subject_id, case_id)."""
    schema = ws.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    cid = add_candidate(schema, subject_id, source_url="https://instagram.com/badactor/p/1")
    r = client.post(
        f"/workspaces/{ws.id}/review/candidates/{cid}/confirm",
        headers=hdr,
        json={"claim_type": "likeness"},
    )
    assert r.status_code == 201, r.text
    return subject_id, r.json()["id"]


def test_open_case_lists_with_offender_key_and_timeline(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    _subject, case_id = _open_case(client, new_workspace, hdr)

    listing = client.get(f"/workspaces/{new_workspace.id}/cases", headers=hdr)
    assert listing.status_code == 200
    row = next(c for c in listing.json() if c["id"] == case_id)
    assert row["status"] == "confirmed"
    assert row["offender_key"] == "instagram:@badactor"
    assert row["overdue"] is False  # due 2 days out per config

    detail = client.get(f"/workspaces/{new_workspace.id}/cases/{case_id}", headers=hdr).json()
    assert detail["allowed_transitions"] == ["filed"]
    assert any(e["kind"] == "created" for e in detail["timeline"])


def test_transition_flow_and_illegal_rejected(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    _subject, case_id = _open_case(client, new_workspace, hdr)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}"

    assert (
        client.post(f"{base}/transition", headers=hdr, json={"to_status": "filed"}).status_code
        == 200
    )
    detail = client.get(base, headers=hdr).json()
    assert sorted(detail["allowed_transitions"]) == [
        "countered",
        "escalated",
        "removed",
        "withdrawn",
    ]

    assert (
        client.post(f"{base}/transition", headers=hdr, json={"to_status": "removed"}).status_code
        == 200
    )
    # removed → filed is illegal.
    bad = client.post(f"{base}/transition", headers=hdr, json={"to_status": "filed"})
    assert bad.status_code == 422


def test_claim_change_locked_after_filed(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    _subject, case_id = _open_case(client, new_workspace, hdr)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}"

    # Editable while confirmed (ncii is supported via enforcement consent).
    ok = client.post(
        f"{base}/claim", headers=hdr, json={"claim_type": "ncii", "note": "better fit"}
    )
    assert ok.status_code == 200 and ok.json()["claim_type"] == "ncii"

    client.post(f"{base}/transition", headers=hdr, json={"to_status": "filed"})
    locked = client.post(f"{base}/claim", headers=hdr, json={"claim_type": "likeness", "note": "x"})
    assert locked.status_code == 422


def test_withdraw_then_refile_links_both_cases(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    _subject, case_id = _open_case(client, new_workspace, hdr)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}"
    client.post(f"{base}/transition", headers=hdr, json={"to_status": "filed"})
    client.post(
        f"{base}/transition", headers=hdr, json={"to_status": "withdrawn", "note": "wrong claim"}
    )

    refile = client.post(
        f"{base}/refile", headers=hdr, json={"claim_type": "ncii", "note": "refile"}
    )
    assert refile.status_code == 201, refile.text
    new_id = refile.json()["id"]
    assert new_id != case_id and refile.json()["claim_type"] == "ncii"

    # Both timelines carry a reciprocal link event.
    old_tl = client.get(base, headers=hdr).json()["timeline"]
    new_tl = client.get(f"/workspaces/{new_workspace.id}/cases/{new_id}", headers=hdr).json()[
        "timeline"
    ]
    assert any(e["kind"] == "link" and e["related_case_id"] == new_id for e in old_tl)
    assert any(e["kind"] == "link" and e["related_case_id"] == case_id for e in new_tl)


def test_notes_and_assignment(
    client: TestClient, new_workspace: Workspace, auth_header: Auth, db
) -> None:
    hdr = auth_header("admin_user")
    _subject, case_id = _open_case(client, new_workspace, hdr)
    base = f"/workspaces/{new_workspace.id}/cases/{case_id}"

    note = client.post(f"{base}/notes", headers=hdr, json={"body": "called the host"})
    assert note.status_code == 201
    assert any(
        n["body"] == "called the host" for n in client.get(base, headers=hdr).json()["notes"]
    )

    good = client.post(f"{base}/assign", headers=hdr, json={"staff_id": db.admin_staff_id})
    assert good.status_code == 200 and good.json()["assigned_staff_id"] == db.admin_staff_id
    bad = client.post(f"{base}/assign", headers=hdr, json={"staff_id": 999999})
    assert bad.status_code == 422  # nonexistent staff


def test_assign_rejects_staff_without_workspace_access(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    """A real staffer who lacks access to THIS workspace can't be assigned (privilege guard)."""
    import uuid

    from api.app.models.public import StaffRole
    from api.app.services.staff import create_staff

    hdr = auth_header("admin_user")
    _subject, case_id = _open_case(client, new_workspace, hdr)
    outsider = create_staff(
        clerk_user_id=f"outsider_{uuid.uuid4().hex[:8]}",
        email="outsider@vg.test",
        role=StaffRole.reviewer,  # no grant to new_workspace
    )
    r = client.post(
        f"/workspaces/{new_workspace.id}/cases/{case_id}/assign",
        headers=hdr,
        json={"staff_id": outsider.id},
    )
    assert r.status_code == 422


def test_overdue_filter_and_offender_summary(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    make_case(
        schema,
        subject_id,
        status=CaseStatus.filed,
        offender_key="domain:x.example",
        due_at=past_due(),
    )
    make_case(schema, subject_id, status=CaseStatus.confirmed, offender_key="domain:y.example")

    overdue = client.get(f"/workspaces/{new_workspace.id}/cases?overdue=true", headers=hdr).json()
    assert len(overdue) == 1 and overdue[0]["overdue"] is True

    offenders = client.get(f"/workspaces/{new_workspace.id}/cases/offenders", headers=hdr).json()
    keys = {g["offender_key"] for g in offenders}
    assert {"domain:x.example", "domain:y.example"} <= keys
