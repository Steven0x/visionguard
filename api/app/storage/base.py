"""Storage interface. Implementations: S3Storage (MinIO in dev/tests, R2 in prod)."""

from __future__ import annotations

from typing import Protocol


class Storage(Protocol):
    def ensure_bucket(self) -> None:
        """Create the bucket if it does not already exist (idempotent)."""
        ...

    def put_object(self, key: str, data: bytes, content_type: str) -> None: ...

    def get_object(self, key: str) -> bytes:
        """Read an object's bytes (used by the worker to fingerprint an original)."""
        ...

    def generate_download_url(
        self, key: str, *, filename: str, expires_in: int
    ) -> str:
        """A short-lived presigned GET URL with an attachment disposition."""
        ...

    def delete_object(self, key: str) -> None: ...
