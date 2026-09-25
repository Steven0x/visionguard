"""Storage factory."""

from __future__ import annotations

from functools import lru_cache

from api.app.config import get_settings
from api.app.storage.base import Storage
from api.app.storage.s3 import S3Storage


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "fake":
        from api.app.storage.fake import FakeStorage

        return FakeStorage()
    return S3Storage(settings)


__all__ = ["Storage", "get_storage"]
