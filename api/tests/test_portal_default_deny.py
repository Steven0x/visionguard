"""Default-deny guardrail (Slice 12): every registered route rejects an agency token with 403,
except the portal surface, GET /me, and the unauthenticated health/docs routes. This walks the
whole OpenAPI route table, so a future staff route that forgets its role gate fails CI."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from api.app.main import app
from api.app.models.public import Workspace
from api.tests.portalhelpers import make_agency_user

# Unauthenticated / non-staff routes that are not expected to 403.
# /billing/webhook is unauthenticated BY DESIGN (Stripe signature-gated, no staff/agency identity),
# so it is explicitly allowlisted here (it returns 400 on a bad signature, never 403).
_UNAUTH = {
    "/healthz",
    "/readyz",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/billing/webhook",
}


def _concrete(path: str, workspace_id: int) -> str:
    path = path.replace("{workspace_id}", str(workspace_id))
    return re.sub(r"{[^}]+}", "1", path)


def test_agency_token_is_denied_on_every_staff_route(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    make_agency_user(
        clerk_user_id="agency_deny",
        email="deny@agency.test",
        workspace_id=new_workspace.id,
    )
    hdr = auth_header("agency_deny")
    paths = app.openapi()["paths"]

    checked = 0
    failures: list[tuple[str, str, int]] = []
    for path, methods in paths.items():
        if path in _UNAUTH or path.startswith("/portal"):
            continue
        url = _concrete(path, new_workspace.id)
        for method in methods:
            if path == "/me" and method == "get":
                continue  # the portal reads its own identity here
            kwargs = {"headers": hdr}
            if method in ("post", "put", "patch"):
                kwargs["json"] = {}
            resp = client.request(method.upper(), url, **kwargs)
            checked += 1
            if resp.status_code != 403:
                failures.append((method.upper(), path, resp.status_code))

    assert checked > 50, f"expected to walk the full route table, only saw {checked}"
    assert not failures, f"routes that did not 403 for an agency token: {failures}"


def test_me_review_prefs_is_denied_for_agency(
    client: TestClient, new_workspace: Workspace, auth_header
) -> None:
    make_agency_user(
        clerk_user_id="agency_prefs",
        email="prefs@agency.test",
        workspace_id=new_workspace.id,
    )
    hdr = auth_header("agency_prefs")
    assert client.get("/me", headers=hdr).status_code == 200  # own identity is allowed
    r = client.put("/me/review-prefs", headers=hdr, json={"keep_blur": False})
    assert r.status_code == 403
