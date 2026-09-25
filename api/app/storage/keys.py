"""Tenant-scoped, unguessable object keys."""

from __future__ import annotations

import uuid

from api.app.db.base import validate_schema_name

_EXT_BY_TYPE = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_KINDS = {"rights", "consent", "authorization", "asset", "thumbnail"}


def object_key(schema: str, kind: str, content_type: str) -> str:
    """Build ``{ws_schema}/{kind}/{uuid}.{ext}``. Schema is validated; uuid makes it
    unguessable so keys can't be walked across tenants."""
    validate_schema_name(schema)
    if kind not in _KINDS:
        raise ValueError(f"unknown object kind: {kind!r}")
    ext = _EXT_BY_TYPE.get(content_type, "bin")
    return f"{schema}/{kind}/{uuid.uuid4().hex}.{ext}"
