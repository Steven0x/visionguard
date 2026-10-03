"""S3-compatible storage via boto3. Works against MinIO (dev/tests) and Cloudflare R2."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from api.app.config import Settings


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.storage_bucket
        self._settings = settings
        self._client = self._make_client(settings.storage_endpoint_url or None)
        # Dev-only: presign against a public endpoint (e.g. a cloudflared tunnel to MinIO) so an
        # external fetcher like Lens can reach the asset. Keyed by endpoint so the client is reused.
        self._signing_clients: dict[str, Any] = {}

    def _make_client(self, endpoint_url: str | None) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self._settings.storage_access_key_id,
            aws_secret_access_key=self._settings.storage_secret_access_key,
            region_name=self._settings.storage_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _signing_client(self, public_base_url: str | None) -> Any:
        if not public_base_url:
            return self._client
        client = self._signing_clients.get(public_base_url)
        if client is None:
            client = self._make_client(public_base_url)
            self._signing_clients[public_base_url] = client
        return client

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def bucket_reachable(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:  # noqa: BLE001 - readiness probe: any failure means not reachable
            return False

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    def get_object(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def generate_download_url(
        self, key: str, *, filename: str, expires_in: int, public_base_url: str | None = None
    ) -> str:
        # Quote the filename to keep the header well-formed.
        safe = filename.replace('"', "")
        # When a public base is given (dev tunnel), SIGN against that endpoint so the SigV4 host in
        # the signature matches what the external fetcher connects to. The tunnel forwards to MinIO.
        return self._signing_client(public_base_url).generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{safe}"',
            },
            ExpiresIn=expires_in,
        )

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
