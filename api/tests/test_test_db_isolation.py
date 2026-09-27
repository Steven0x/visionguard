"""Guards that the test suite runs against a dedicated *_test database, never the dev DB."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from api.app.config import get_settings
from api.tests.conftest import _derive_test_url


def test_suite_runs_against_a_test_database() -> None:
    name = make_url(get_settings().database_url).database or ""
    assert name.endswith("_test"), f"tests must use a *_test database, got {name!r}"
    assert name != "visionguard", "tests must never run against the dev database"


def test_derive_test_url_appends_suffix_and_is_idempotent() -> None:
    dev = "postgresql+psycopg://u:p@localhost:5433/visionguard"
    assert _derive_test_url(dev).endswith("/visionguard_test")
    # Already a test db → unchanged.
    already = "postgresql+psycopg://u:p@localhost:5433/visionguard_test"
    assert _derive_test_url(already).endswith("/visionguard_test")
    # Any other db name also gets the suffix (so we can't accidentally hit a real db).
    assert _derive_test_url("postgresql+psycopg://u:p@h/prod").endswith("/prod_test")
