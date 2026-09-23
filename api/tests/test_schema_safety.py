"""Tenant schema names are derived + validated, never taken from raw input."""

from __future__ import annotations

import pytest

from api.app.db.base import schema_for_workspace, validate_schema_name
from api.app.db.session import tenant_session


def test_valid_ids_produce_expected_schema() -> None:
    assert schema_for_workspace(5) == "ws_5"
    assert validate_schema_name("ws_42") == "ws_42"


@pytest.mark.parametrize(
    "bad",
    [
        "1; DROP SCHEMA public CASCADE; --",
        "public",
        "ws_1; DROP SCHEMA public",
        "ws-1",
        "WS_1",
        "ws_1 ",
        "",
    ],
)
def test_malicious_or_malformed_names_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_schema_name(bad)


def test_schema_for_workspace_rejects_injection() -> None:
    with pytest.raises(ValueError):
        schema_for_workspace("1; DROP SCHEMA public CASCADE; --")


def test_tenant_session_validates_schema() -> None:
    with pytest.raises(ValueError):
        with tenant_session("public"):
            pass
