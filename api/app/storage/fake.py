"""In-memory Storage for tests/CI — no MinIO/R2 container required.

Process-local: because get_storage() is cached, the TestClient app, the (eager) worker, and
direct callers all share one instance within a test process.
"""

from __future__ import annotations


class FakeStorage:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        pass

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = data

    def get_object(self, key: str) -> bytes:
        return self._objects[key]

    def generate_download_url(self, key: str, *, filename: str, expires_in: int) -> str:
        return f"http://fake-storage.local/{key}?filename={filename}&expires={expires_in}"

    def delete_object(self, key: str) -> None:
        self._objects.pop(key, None)
