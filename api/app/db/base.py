"""Declarative bases and tenant-schema naming rules.

Two bases:
  * ``PublicBase`` — shared tables in the ``public`` schema (Workspace, Staff, ...).
  * ``TenantBase`` — per-tenant tables. Their tables carry the SYMBOLIC schema name
    ``"tenant"``; at runtime SQLAlchemy's ``schema_translate_map`` rewrites that token to
    the workspace's real schema (``ws_<id>``). See ``db/tenant.py``.

Schema names are ALWAYS derived from a trusted workspace id and validated against
``SCHEMA_RE`` before they touch DDL or a translate map — never taken from client input.
"""

from __future__ import annotations

import re

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# The symbolic token tenant tables declare as their schema.
TENANT_SCHEMA_TOKEN = "tenant"  # noqa: S105 - schema token, not a secret

# Real tenant schema names must look exactly like this. Anything else is rejected
# before a CREATE SCHEMA or schema_translate_map bind, so a hostile id can't inject SQL.
SCHEMA_RE = re.compile(r"^ws_[a-z0-9_]+$")


class PublicBase(DeclarativeBase):
    metadata = MetaData()


class TenantBase(DeclarativeBase):
    metadata = MetaData(schema=TENANT_SCHEMA_TOKEN)


def validate_schema_name(name: str) -> str:
    """Return ``name`` if it is a well-formed tenant schema, else raise ``ValueError``."""
    if not isinstance(name, str) or not SCHEMA_RE.fullmatch(name):
        raise ValueError(f"unsafe tenant schema name: {name!r}")
    return name


def schema_for_workspace(workspace_id: int | str) -> str:
    """Derive and validate the schema name for a workspace id."""
    return validate_schema_name(f"ws_{workspace_id}")
