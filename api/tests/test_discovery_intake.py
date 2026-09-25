"""Manual URL intake: canonicalize, dedupe, max-batch."""

from __future__ import annotations

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.tests.discohelpers import authorized_subject


def _intake(client, auth_header, db, ws, sid, urls):
    return client.post(
        f"/workspaces/{ws.id}/subjects/{sid}/discovery/intake",
        headers=auth_header(db.admin_user_id),
        json={"urls": urls},
    )


def test_intake_canonicalizes_and_dedupes(client, auth_header, db, new_workspace):
    sid, _ = authorized_subject(new_workspace.schema_name)
    urls = [
        "https://Example.com/a?utm_source=news",  # canonical https://example.com/a
        "https://example.com/a",  # duplicate of the above after canonicalization
        "http://ok.test/b",
        "not-a-url",  # dropped
        "ftp://x/y",  # dropped (scheme)
    ]
    res = _intake(client, auth_header, db, new_workspace, sid, urls)
    assert res.status_code == 200
    assert res.json()["candidates_found"] == 2

    listed = client.get(
        f"/workspaces/{new_workspace.id}/subjects/{sid}/discovery/candidates",
        headers=auth_header(db.admin_user_id),
    ).json()
    sources = {c["source_url"] for c in listed}
    assert sources == {"https://example.com/a", "http://ok.test/b"}
    assert all(c["kind"] == "link" for c in listed)

    with tenant_session(new_workspace.schema_name) as s:
        assert "discovery.intake" in set(s.scalars(select(AuditLog.action)).all())


def test_intake_rejects_over_max(client, auth_header, db, new_workspace):
    sid, _ = authorized_subject(new_workspace.schema_name)
    urls = [f"https://x.test/{i}" for i in range(201)]
    res = _intake(client, auth_header, db, new_workspace, sid, urls)
    assert res.status_code == 422
