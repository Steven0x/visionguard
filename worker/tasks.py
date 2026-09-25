"""Celery tasks."""

from __future__ import annotations

import io

from api.app.db.base import schema_for_workspace
from api.app.db.session import tenant_session
from api.app.fingerprint import embedder as embedder_mod
from api.app.fingerprint.hashing import phash_hex, sha256_hex
from api.app.models.assets import Asset, AssetStatus
from api.app.storage import get_storage
from PIL import Image
from sqlalchemy import select, update

from worker.celery_app import celery


@celery.task(name="worker.ping")
def ping() -> str:
    return "pong"


@celery.task(name="worker.fingerprint_asset")
def fingerprint_asset(workspace_id: int, asset_id: int) -> str:
    """Fingerprint one asset. Atomically claims it, swallows errors (never raises)."""
    schema = schema_for_workspace(workspace_id)

    # Atomic claim: only the worker that flips pending→processing proceeds.
    with tenant_session(schema) as session:
        result = session.execute(
            update(Asset)
            .where(Asset.id == asset_id, Asset.status == AssetStatus.pending)
            .values(status=AssetStatus.processing)
        )
        claimed = result.rowcount  # type: ignore[attr-defined]
    if not claimed:
        return "skipped"

    try:
        with tenant_session(schema) as session:
            asset = session.get(Asset, asset_id)
            if asset is None:
                return "missing"
            file_key = asset.file_key

        data = get_storage().get_object(file_key)
        digest = sha256_hex(data)
        image = Image.open(io.BytesIO(data))
        phash = phash_hex(image)
        embedding = embedder_mod.get_embedder().embed(data)

        with tenant_session(schema) as session:
            asset = session.get(Asset, asset_id)
            if asset is None:
                return "missing"
            asset.sha256 = digest
            asset.phash = phash
            asset.embedding = embedding
            # Exact-duplicate detection: earliest ready asset with the same content hash.
            asset.duplicate_of_asset_id = session.scalar(
                select(Asset.id)
                .where(
                    Asset.sha256 == digest,
                    Asset.id != asset_id,
                    Asset.status == AssetStatus.ready,
                )
                .order_by(Asset.id)
                .limit(1)
            )
            asset.error = None
            asset.status = AssetStatus.ready
        return "ready"
    except Exception as exc:  # never raises — eager-safe; failure is a recorded state
        with tenant_session(schema) as session:
            asset = session.get(Asset, asset_id)
            if asset is not None:
                asset.attempts += 1
                asset.error = str(exc)[:1000]
                asset.status = AssetStatus.failed
        return "failed"
