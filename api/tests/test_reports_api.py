"""Reports & internal-metrics API (Slice 10): generate/list/download a report (download audited),
the metrics summary, role gating, and validation errors."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.public import Workspace
from api.tests.conftest import Fixtures
from api.tests.reviewhelpers import make_subject

Auth = Callable[..., dict[str, str]]


def test_generate_list_and_download_report(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    make_subject(new_workspace.schema_name)
    base = f"/workspaces/{new_workspace.id}/reports"

    gen = client.post(base, headers=hdr, json={"start": "2026-01-01", "end": "2026-01-31"})
    assert gen.status_code == 201, gen.text
    rid = gen.json()["id"]
    assert len(gen.json()["pdf_sha256"]) == 64

    listing = client.get(base, headers=hdr)
    assert listing.status_code == 200
    assert any(r["id"] == rid for r in listing.json())

    pdf = client.get(f"{base}/{rid}.pdf", headers=hdr)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"

    inputs = client.get(f"{base}/{rid}/inputs.json", headers=hdr)
    assert inputs.status_code == 200
    assert inputs.json()["period_start"] == "2026-01-01"

    # Both downloads are audited.
    with tenant_session(new_workspace.schema_name) as s:
        actions = set(
            s.scalars(
                select(AuditLog.action).where(AuditLog.entity_type == "report")
            ).all()
        )
    assert {"report.generated", "report.downloaded"} <= actions


def test_generate_rejects_bad_range(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    r = client.post(
        f"/workspaces/{new_workspace.id}/reports", headers=hdr,
        json={"start": "2026-02-01", "end": "2026-01-01"},
    )
    assert r.status_code == 422


def test_report_unknown_subject_404(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    r = client.post(
        f"/workspaces/{new_workspace.id}/reports", headers=hdr,
        json={"subject_id": 999999, "start": "2026-01-01", "end": "2026-01-31"},
    )
    assert r.status_code == 404  # unknown subject → not found (distinct from a bad range → 422)


def test_report_not_downloadable_cross_workspace(
    client: TestClient, new_workspace: Workspace, db: Fixtures, auth_header: Auth
) -> None:
    """A report generated in one workspace is not reachable under another workspace's id — its
    row lives only in the generating workspace's schema, so the id 404s elsewhere."""
    hdr = auth_header("admin_user")  # admin has all-workspaces access
    make_subject(new_workspace.schema_name)
    gen = client.post(
        f"/workspaces/{new_workspace.id}/reports", headers=hdr,
        json={"start": "2026-01-01", "end": "2026-01-31"},
    )
    assert gen.status_code == 201
    rid = gen.json()["id"]

    other = db.workspace_a if db.workspace_a.id != new_workspace.id else db.workspace_b
    cross = client.get(f"/workspaces/{other.id}/reports/{rid}.pdf", headers=hdr)
    assert cross.status_code == 404


def test_metrics_summary_endpoint(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    hdr = auth_header("admin_user")
    r = client.get(f"/workspaces/{new_workspace.id}/metrics/summary", headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert "removals" in body and "provider_cost" in body
    assert body["review_precision"] is None  # no filings yet


def test_reports_require_workspace_access(
    client: TestClient, new_workspace: Workspace, auth_header: Auth
) -> None:
    # A reviewer with no grant to this workspace is refused.
    hdr = auth_header("reviewer_none")
    r = client.get(f"/workspaces/{new_workspace.id}/reports", headers=hdr)
    assert r.status_code == 403
