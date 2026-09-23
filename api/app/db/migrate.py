"""Programmatic Alembic entry point used by the CLI and by workspace provisioning."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from api.app.config import get_settings

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def upgrade_all() -> None:
    """Upgrade the public schema and every tenant schema to head.

    Idempotent: schemas already at head are no-ops. env.py runs the public pass first,
    then loops the tenant schemas listed in ``public.workspaces``.
    """
    command.upgrade(_config(), "head")
