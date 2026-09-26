"""Write-once evidence storage (CLAUDE.md #6). Evidence is never edited or overwritten — only
superseded by a new capture. `seal_object` refuses to overwrite an existing key; on S3/R2/MinIO
it also writes with object-lock retention. The fake refuses overwrites so tests prove it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol

from api.app.config import Settings, get_settings


class EvidenceExists(Exception):
    """Raised when sealing would overwrite an existing evidence object (write-once)."""


class EvidenceStorage(Protocol):
    def ensure_bucket(self) -> None: ...
    def seal_object(self, key: str, data: bytes, content_type: str) -> None: ...
    def get_object(self, key: str) -> bytes: ...
    def generate_download_url(self, key: str, *, filename: str, expires_in: int) -> str: ...


class S3EvidenceStorage:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self._settings = settings
        self._bucket = settings.storage_evidence_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url or None,
            aws_access_key_id=settings.storage_access_key_id,
            aws_secret_access_key=settings.storage_secret_access_key,
            region_name=settings.storage_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            # Object lock requires versioning; it can only be enabled at creation time.
            self._client.create_bucket(
                Bucket=self._bucket, ObjectLockEnabledForBucket=True
            )

    def _exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def seal_object(self, key: str, data: bytes, content_type: str) -> None:
        if self._exists(key):
            raise EvidenceExists(f"evidence object already exists (write-once): {key}")
        retain_until = datetime.now(UTC) + timedelta(days=self._settings.evidence_retention_days)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ObjectLockMode=self._settings.evidence_object_lock_mode,
            ObjectLockRetainUntilDate=retain_until,
        )

    def get_object(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def generate_download_url(self, key: str, *, filename: str, expires_in: int) -> str:
        safe = filename.replace('"', "")
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{safe}"',
            },
            ExpiresIn=expires_in,
        )


class FakeEvidenceStorage:
    """In-memory, write-once. Shared per process (get_evidence_storage is cached)."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        pass

    def seal_object(self, key: str, data: bytes, content_type: str) -> None:
        if key in self._objects:
            raise EvidenceExists(f"evidence object already exists (write-once): {key}")
        self._objects[key] = data

    def get_object(self, key: str) -> bytes:
        return self._objects[key]

    def generate_download_url(self, key: str, *, filename: str, expires_in: int) -> str:
        return f"http://fake-evidence.local/{key}?filename={filename}&expires={expires_in}"


@lru_cache
def get_evidence_storage() -> EvidenceStorage:
    settings = get_settings()
    if settings.storage_backend == "fake":
        return FakeEvidenceStorage()
    return S3EvidenceStorage(settings)
