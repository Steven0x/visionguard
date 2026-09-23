"""Authentication + role enforcement."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app.auth.deps import require_role
from api.app.models.public import Staff, StaffRole
from api.tests.conftest import Fixtures

Header = Callable[..., dict[str, str]]


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/me").status_code == 401


def test_me_rejects_valid_token_for_unknown_staff(
    client: TestClient, auth_header: Header
) -> None:
    # A valid Clerk identity with no Staff row must NOT be auto-provisioned.
    res = client.get("/me", headers=auth_header("ghost_user"))
    assert res.status_code == 403


def test_me_ok_for_known_staff(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.get("/me", headers=auth_header(db.admin_user_id))
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "admin@visionguard.test"
    assert body["role"] == "admin"


def test_me_rejects_disallowed_azp(
    client: TestClient, auth_header: Header, db: Fixtures
) -> None:
    res = client.get(
        "/me", headers=auth_header(db.admin_user_id, azp="http://evil.example")
    )
    assert res.status_code == 401


def test_require_role_rejects_wrong_role() -> None:
    # Unit check of the role gate: a reviewer cannot pass an admin-only dependency.
    dep = require_role(StaffRole.admin)
    reviewer = Staff(
        id=1,
        clerk_user_id="x",
        email="r@visionguard.test",
        role=StaffRole.reviewer,
        all_workspaces=False,
    )
    with pytest.raises(HTTPException) as exc:
        dep(staff=reviewer)
    assert exc.value.status_code == 403
