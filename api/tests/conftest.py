"""Shared test fixtures.

These tests need a real Postgres (schema-per-tenant + JSONB). Locally: `make infra-up`.
CI provides one as a service container. AUTH_TEST_MODE is on so tokens are local HS256
JWTs minted by ``make_test_token`` — no live Clerk required.
"""

from __future__ import annotations

import os

# The suite must be HERMETIC: `make test` does `include .env; export`, so a developer's dev/demo
# .env (e.g. AUTH_TEST_MODE=0, APP_ENV=dev, STORAGE_BACKEND=s3 for the local Clerk demo) would
# otherwise leak in and break the suite. Force the test-critical values (override any inherited
# env) BEFORE any app module reads settings. CI sets the same fake values, so this is a no-op there.
os.environ.update(
    {
        "APP_ENV": "test",
        "AUTH_TEST_MODE": "1",
        "EMBEDDER_BACKEND": "fake",  # no torch / weight downloads
        "STORAGE_BACKEND": "fake",  # in-memory; no MinIO/R2
        "FETCHER_BACKEND": "fake",  # no network
        "PROVIDER_BACKEND": "fake",
        "CAPTURE_BACKEND": "fake",  # no browser
        "TSA_BACKEND": "fake",  # no TSA/network
        "CSAM_SCANNER_BACKEND": "fake",  # dev/test-only scanner
    }
)
os.environ.setdefault("CSAM_FAKE_RESULT", "clean")  # individual tests flip this at runtime

# ── Dedicated TEST database — the suite must NEVER touch the dev database ──────
# We derive a "<name>_test" database from whatever DATABASE_URL is configured (so `make test`,
# which exports the dev .env, still targets visionguard_test, not visionguard), refuse to run if
# the target isn't a *_test database, and auto-create it on the same Postgres server.
from sqlalchemy import create_engine as _create_engine  # noqa: E402
from sqlalchemy import text as _text  # noqa: E402
from sqlalchemy.engine import make_url as _make_url  # noqa: E402

_DEFAULT_DB_URL = "postgresql+psycopg://visionguard:visionguard@localhost:5433/visionguard"


def _derive_test_url(raw: str) -> str:
    url = _make_url(raw)
    name = url.database or ""
    if not name.endswith("_test"):
        name = f"{name}_test"
    return url.set(database=name).render_as_string(hide_password=False)


_TEST_DB_URL = _derive_test_url(os.environ.get("DATABASE_URL", _DEFAULT_DB_URL))
_TEST_DB_NAME = _make_url(_TEST_DB_URL).database or ""
# Refuse to run against the dev db name or anything not clearly a test database.
if _TEST_DB_NAME in {"visionguard", ""} or not _TEST_DB_NAME.endswith("_test"):
    raise RuntimeError(
        f"refusing to run the test suite against non-test database {_TEST_DB_NAME!r}; "
        "the test database name must end in '_test'"
    )
if not _TEST_DB_NAME.replace("_", "").isalnum():  # guard the CREATE DATABASE interpolation
    raise RuntimeError(f"unsafe test database name {_TEST_DB_NAME!r}")
os.environ["DATABASE_URL"] = _TEST_DB_URL


def _ensure_test_database() -> None:
    """Create the *_test database if it doesn't exist (connect via the 'postgres' maint db)."""
    url = _make_url(_TEST_DB_URL)
    admin = _create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            found = conn.execute(
                _text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            ).scalar()
            if not found:
                conn.execute(_text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


_ensure_test_database()

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
    admin_staff_id: int
    reviewer_a_user_id: str
    reviewer_a_staff_id: int
    reviewer_none_user_id: str


def _reset_database() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        tenant_schemas: list[str] = list(
            conn.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name LIKE 'ws\\_%' ESCAPE '\\'"
                )
            ).scalars().all()
        )
    # Drop each tenant schema in its OWN transaction — dropping many HNSW-indexed schemas in
    # a single transaction exhausts Postgres shared memory (locks).
    for schema in tenant_schemas:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def db() -> Fixtures:
    _reset_database()
    upgrade_all()  # build the public schema

    # Ensure the object-storage bucket exists (MinIO in dev/tests).
    from api.app.storage import get_storage

    get_storage().ensure_bucket()

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

    return Fixtures(
        workspace_a=workspace_a,
        workspace_b=workspace_b,
        admin_user_id="admin_user",
        admin_staff_id=admin.id,
        reviewer_a_user_id="reviewer_a",
        reviewer_a_staff_id=reviewer_a.id,
        reviewer_none_user_id="reviewer_none",
    )


@pytest.fixture
def client(db: Fixtures) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def new_workspace(db: Fixtures) -> Workspace:
    """A freshly provisioned workspace (empty tenant schema) for pollution-free tests.

    The seeded admin has all-workspaces access, so admin tokens can reach it immediately.
    """
    import uuid

    from api.app.services.workspaces import create_workspace_with_access

    slug = f"t-{uuid.uuid4().hex[:10]}"
    return create_workspace_with_access(
        name=f"Fresh {slug}", creator_staff_id=db.admin_staff_id, slug=slug
    )


# Matches the default ALLOWED_ORIGINS so tokens carry a valid authorized-party claim.
DEFAULT_TEST_AZP = "http://localhost:5173"


@pytest.fixture
def auth_header() -> Callable[..., dict[str, str]]:
    def _make(
        clerk_user_id: str, *, azp: str | None = DEFAULT_TEST_AZP
    ) -> dict[str, str]:
        token = make_test_token(clerk_user_id, azp=azp)
        return {"Authorization": f"Bearer {token}"}

    return _make
