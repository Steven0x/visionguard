"""Engine and session factories for the public schema and per-tenant sessions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.app.config import get_settings
from api.app.db.base import TENANT_SCHEMA_TOKEN, validate_schema_name


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, future=True, pool_pre_ping=True)


@lru_cache
def _sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)


@contextmanager
def public_session() -> Iterator[Session]:
    """A session for shared/public tables (workspaces, staff)."""
    session = _sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def tenant_session(schema: str) -> Iterator[Session]:
    """A session scoped to one workspace's schema.

    The connection is bound with ``schema_translate_map`` so every tenant table resolves
    to ``schema`` and to nothing else — a session opened for workspace B cannot address
    workspace A's data. The schema name is validated first.
    """
    validate_schema_name(schema)
    connection = get_engine().connect().execution_options(
        schema_translate_map={TENANT_SCHEMA_TOKEN: schema}
    )
    session = Session(bind=connection, future=True, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        connection.close()
