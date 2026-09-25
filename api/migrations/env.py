"""Alembic environment: migrate the public schema, then every tenant schema.

One linear migration history drives all schemas. Each pass sets a scope
(``public`` / ``tenant``) and its real schema name; migrations guard on the scope so they
only touch tables that belong to it. Per-schema ``alembic_version`` tables (via
``version_table_schema``) track each schema independently.
"""

from __future__ import annotations

# Ensure all model metadata is registered on the bases.
import api.app.models  # noqa: F401
from alembic import context
from api.app.config import get_settings
from api.app.db.base import (
    TENANT_SCHEMA_TOKEN,
    PublicBase,
    TenantBase,
    schema_for_workspace,
)
from api.app.db.migration_scope import set_current
from api.app.db.session import get_engine
from sqlalchemy import Connection, Engine, MetaData, inspect, text

config = context.config


def _list_tenant_schemas(connection: Connection) -> list[str]:
    """Schema names for every provisioned workspace that has a schema in the DB."""
    insp = inspect(connection)
    if not insp.has_table("workspaces", schema="public"):
        return []
    existing = set(insp.get_schema_names())
    ids: list[int] = list(
        connection.execute(text("SELECT id FROM public.workspaces ORDER BY id")).scalars().all()
    )
    return [s for wid in ids if (s := schema_for_workspace(wid)) in existing]


def _run_for_scope(
    engine: Engine, scope: str, schema: str, metadata: MetaData
) -> None:
    # A FRESH connection per scope: each pass gets its own transaction that alembic begins
    # and commits. (Reusing one connection across scopes leaves the tenant DDL uncommitted.)
    translate = {TENANT_SCHEMA_TOKEN: schema if scope == "tenant" else None}
    set_current(scope, schema)
    with engine.connect() as connection:
        context.configure(
            connection=connection.execution_options(schema_translate_map=translate),
            target_metadata=metadata,
            version_table_schema=schema,
            include_schemas=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    engine = get_engine()
    # Public/shared tables first, so the tenant enumeration can read public.workspaces.
    _run_for_scope(engine, "public", "public", PublicBase.metadata)
    with engine.connect() as connection:
        schemas = _list_tenant_schemas(connection)
    for schema in schemas:
        _run_for_scope(engine, "tenant", schema, TenantBase.metadata)


def run_migrations_offline() -> None:  # pragma: no cover - we always run online
    raise NotImplementedError(
        "VisionGuard migrations run online (multi-schema); use `vg migrate`."
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
