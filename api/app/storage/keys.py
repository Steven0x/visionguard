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
_KINDS = {
    "rights",
    "consent",
    "authorization",
    "asset",
    "thumbnail",
    "candidate_thumbnail",
    # Slice 12: an agency-uploaded "Needs from you" PDF. Lives under a quarantine/ prefix that
    # nothing renders inline — staff download only, and its embedded images are CSAM-scanned first.
    "needs_response",
}
# Outsider-supplied kinds that must never be served inline: they get a quarantine/ prefix.
_QUARANTINED_KINDS = {"needs_response"}


def object_key(schema: str, kind: str, content_type: str) -> str:
    """Build ``{ws_schema}/{kind}/{uuid}.{ext}`` (quarantined kinds get a ``quarantine/`` prefix).
    Schema is validated; uuid makes it unguessable so keys can't be walked across tenants."""
    validate_schema_name(schema)
    if kind not in _KINDS:
        raise ValueError(f"unknown object kind: {kind!r}")
    ext = _EXT_BY_TYPE.get(content_type, "bin")
    prefix = f"{schema}/quarantine/{kind}" if kind in _QUARANTINED_KINDS else f"{schema}/{kind}"
    return f"{prefix}/{uuid.uuid4().hex}.{ext}"
