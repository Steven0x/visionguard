"""Shared test fixtures.

These tests need a real Postgres (schema-per-tenant + JSONB). Locally: `make infra-up`.
CI provides one as a service container. AUTH_TEST_MODE is on so tokens are local HS256
JWTs minted by ``make_test_token`` — no live Clerk required.
"""

from __future__ import annotations

import os

# Must be set before any app module reads settings.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AUTH_TEST_MODE", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://visionguard:visionguard@localhost:5433/visionguard",
)

from collections.abc import Callable, Iterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from api.app.auth.clerk import make_test_token  # noqa: E402
from api.app.db.migrate import upgrade_all  # noqa: E402
from api.app.db.session import get_engine  # noqa: E402
from api.app.main import app  # noqa: E402
from api.app.models.public import StaffRole, Workspace  # noqa: E402
from api.app.services.provisioning import create_workspace  # noqa: E402
from api.app.services.staff import create_staff, grant_workspace_access  # noqa: E402


@dataclass
class Fixtures:
    workspace_a: Workspace
    workspace_b: Workspace
    admin_user_id: str
    reviewer_a_user_id: str
    reviewer_none_user_id: str


def _reset_database() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        tenant_schemas = conn.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'ws\\_%' ESCAPE '\\'"
            )
        ).scalars().all()
        for schema in tenant_schemas:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def db() -> Fixtures:
    _reset_database()
    upgrade_all()  # build the public schema

    workspace_a = create_workspace(name="Agency A", slug="agency-a")
    workspace_b = create_workspace(name="Agency B", slug="agency-b")

    admin = create_staff(
        clerk_user_id="admin_user",
        email="admin@visionguard.test",
        role=StaffRole.admin,
        all_workspaces=True,
    )
    reviewer_a = create_staff(
        clerk_user_id="reviewer_a",
        email="reviewer-a@visionguard.test",
        role=StaffRole.reviewer,
    )
    create_staff(
        clerk_user_id="reviewer_none",
        email="reviewer-none@visionguard.test",
        role=StaffRole.reviewer,
    )
    grant_workspace_access(staff_id=reviewer_a.id, workspace_id=workspace_a.id)

    _ = admin  # created for completeness; identified by clerk id in tests
    return Fixtures(
        workspace_a=workspace_a,
        workspace_b=workspace_b,
        admin_user_id="admin_user",
        reviewer_a_user_id="reviewer_a",
        reviewer_none_user_id="reviewer_none",
    )


@pytest.fixture
def client(db: Fixtures) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_header() -> Callable[[str], dict[str, str]]:
    def _make(clerk_user_id: str, *, azp: str | None = None) -> dict[str, str]:
        token = make_test_token(clerk_user_id, azp=azp)
        return {"Authorization": f"Bearer {token}"}

    return _make
