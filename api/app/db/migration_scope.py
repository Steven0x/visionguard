"""Tiny shared state so migration modules know which pass (public vs a tenant) is running.

``migrations/env.py`` sets this before each ``run_migrations()`` call; individual migrations
read it to act only on their own scope, and to get the real schema name for the rare raw
SQL (e.g. REVOKE) that ``schema_translate_map`` does not rewrite.
"""

from __future__ import annotations

_state: dict[str, str | None] = {"scope": None, "schema": None}


def set_current(scope: str, schema: str) -> None:
    _state["scope"] = scope
    _state["schema"] = schema


def current_scope() -> str | None:
    return _state["scope"]


def current_schema() -> str | None:
    return _state["schema"]
