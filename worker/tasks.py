"""Celery tasks."""

from __future__ import annotations

from api.app.config import get_settings
from api.app.db.base import schema_for_workspace
from api.app.db.session import tenant_session
from api.app.fingerprint import embedder as embedder_mod
from api.app.fingerprint.hashing import phash_hex, sha256_hex

# Imports the Pillow decompression-bomb guard (MAX_IMAGE_PIXELS + warning-as-error) into the
# worker process too, and re-validates the stored bytes rather than a bare Image.open.
from api.app.images import make_thumbnail, validate_and_load
from api.app.models.assets import Asset, AssetStatus
from api.app.services.claim_support import biometric_features_enabled
from api.app.storage import get_storage
from sqlalchemy import select, update

from worker.celery_app import celery


@celery.task(name="worker.ping")
def ping() -> str:
    return "pong"


@celery.task(name="worker.reprocess_asset")
def reprocess_asset(workspace_id: int, asset_id: int) -> str:
    """Re-derive an asset's thumbnail, pHash and embedding from its stored original bytes.

    Used to backfill artifacts after a pipeline change (e.g. the EXIF-orientation fix) without
    re-uploading. Overwrites the existing thumbnail object in place (same key, so signed URLs
    stay valid). The stored original and its sha256 identity never change. Never raises."""
    schema = schema_for_workspace(workspace_id)
    with tenant_session(schema) as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return "missing"
        file_key, thumbnail_key, subject_id = asset.file_key, asset.thumbnail_key, asset.subject_id
        wants_embedding = biometric_features_enabled(session, subject_id)

    try:
        storage = get_storage()
        data = storage.get_object(file_key)
        image = validate_and_load(data)  # EXIF-oriented
        storage.put_object(
            thumbnail_key, make_thumbnail(image, get_settings().thumbnail_max_px), "image/jpeg"
        )
        digest = sha256_hex(data)
        phash = phash_hex(image)
        # CLIP embeddings are gated on biometric consent (CLAUDE.md #1); see fingerprint_asset.
        embedding = embedder_mod.get_embedder().embed(data) if wants_embedding else None

        with tenant_session(schema) as session:
            asset = session.get(Asset, asset_id)
            if asset is None:
                return "missing"
            asset.sha256 = digest
            asset.phash = phash
            asset.embedding = (
                embedding
                if embedding is not None
                and biometric_features_enabled(session, subject_id, for_update=True)
                else None
            )
            asset.error = None
            asset.status = AssetStatus.ready
        return "reprocessed"
    except Exception as exc:  # never raises — mirror fingerprint_asset's recorded-failure state
        with tenant_session(schema) as session:
            asset = session.get(Asset, asset_id)
            if asset is not None:
                asset.error = str(exc)[:1000]
                asset.status = AssetStatus.failed
        return "failed"


@celery.task(name="worker.embed_asset")
def embed_asset(workspace_id: int, asset_id: int) -> str:
    """Compute and store ONLY the CLIP embedding for a ready asset, IF the subject now has
    biometric consent (CLAUDE.md #1). Queued when biometric consent is granted, to backfill
    the embeddings that fingerprinting skipped. Re-checks consent before storing. Never raises."""
    schema = schema_for_workspace(workspace_id)
    with tenant_session(schema) as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.status != AssetStatus.ready:
            return "skipped"
        subject_id, file_key = asset.subject_id, asset.file_key
        if not biometric_features_enabled(session, subject_id):
            return "no_consent"

    try:
        embedding = embedder_mod.get_embedder().embed(get_storage().get_object(file_key))
    except Exception:  # best-effort backfill; leave the asset exact-match-only on failure
        return "failed"

    with tenant_session(schema) as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return "missing"
        # Lock the consent row so a concurrent revoke+purge can't be lost (TOCTOU).
        if not biometric_features_enabled(session, subject_id, for_update=True):
            return "no_consent"
        asset.embedding = embedding
    return "embedded"


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
            subject_id = asset.subject_id
            wants_embedding = biometric_features_enabled(session, subject_id)

        data = get_storage().get_object(file_key)
        digest = sha256_hex(data)
        image = validate_and_load(data)  # bomb-safe decode in the worker process
        phash = phash_hex(image)
        # A whole-image CLIP embedding is treated as biometric (CLAUDE.md #1) until counsel rules;
        # only compute one when the subject has active biometric consent and isn't geo-blocked.
        # Without it the asset is exact-match-only (pHash + rules). See docs/legal/claims-matrix.md.
        embedding = embedder_mod.get_embedder().embed(data) if wants_embedding else None

        with tenant_session(schema) as session:
            asset = session.get(Asset, asset_id)
            # Don't clobber an asset that was deleted or retried out from under this run.
            if asset is None or asset.status != AssetStatus.processing:
                return "stale"
            asset.sha256 = digest
            asset.phash = phash
            # Re-check consent (row-locked) inside this txn so a revoke during compute can't leave
            # an embedding behind (TOCTOU against revoke_consent's purge).
            asset.embedding = (
                embedding
                if embedding is not None
                and biometric_features_enabled(session, subject_id, for_update=True)
                else None
            )
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
