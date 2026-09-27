"""Programmatic Alembic entry point used by the CLI and by workspace provisioning."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from api.app.config import get_settings

_ONLY_SCHEMA_ENV = "VG_MIGRATE_ONLY_SCHEMA"

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def upgrade_all() -> None:
    """Upgrade the public schema and every tenant schema to head.

    Idempotent: schemas already at head are no-ops. env.py runs the public pass first,
    then loops the tenant schemas listed in ``public.workspaces``. Used by ``make migrate``.
    """
    command.upgrade(_config(), "head")


def upgrade_schema(schema: str) -> None:
    """Upgrade ONLY the given tenant schema to head (public assumed already migrated).

    Used by workspace provisioning so creating a workspace doesn't re-migrate every tenant.
    """
    os.environ[_ONLY_SCHEMA_ENV] = schema
    try:
        command.upgrade(_config(), "head")
    finally:
        os.environ.pop(_ONLY_SCHEMA_ENV, None)
