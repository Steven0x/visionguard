"""Asset services: upload (store + thumbnail + enqueue), list, delete, retry."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.csam import ScanOutcome, scan_image
from api.app.images import make_thumbnail, validate_and_load
from api.app.models.assets import Asset, AssetStatus
from api.app.models.csam import CsamSource
from api.app.services.csam_incidents import record_incident
from api.app.storage import get_storage
from api.app.storage.keys import object_key


class AssetDeletionBlocked(Exception):
    """Raised when a guard hook forbids deleting an asset (e.g. referenced by a case)."""


class CsamBlocked(Exception):
    """Raised when an uploaded image fails the CSAM scan; nothing is stored (CLAUDE.md #7)."""


def can_delete_asset(session: Session, asset: Asset) -> bool:
    """False when an open (non-terminal) case references this asset — evidence can't be deleted
    out from under an in-flight enforcement."""
    from api.app.services.review import asset_referenced_by_open_case

    return not asset_referenced_by_open_case(session, asset.id)


def list_assets(session: Session, subject_id: int) -> list[Asset]:
    return list(
        session.scalars(
            select(Asset).where(Asset.subject_id == subject_id).order_by(Asset.id)
        ).all()
    )


def get_asset(session: Session, asset_id: int) -> Asset | None:
    return session.get(Asset, asset_id)


def create_asset(
    session: Session,
    *,
    workspace_id: int,
    schema: str,
    actor_staff_id: int | None,
    subject_id: int,
    data: bytes,
    content_type: str,
    file_name: str,
) -> Asset:
    # Fully decode (decompression-bomb safe) before storing anything; raises InvalidImage.
    image = validate_and_load(data)

    # CSAM gate (CLAUDE.md #7): scan before storing ANY bytes (full-res or thumbnail). Only a
    # `clean` result proceeds; a match records a minimized incident and stores nothing.
    outcome = scan_image(data)
    if outcome is not ScanOutcome.clean:
        if outcome is ScanOutcome.match:
            record_incident(
                session, workspace_id=workspace_id, source=CsamSource.asset_upload,
                sha256=hashlib.sha256(data).hexdigest(), url=None, subject_id=subject_id,
                actor_staff_id=actor_staff_id,
            )
        raise CsamBlocked("image failed the CSAM scan; nothing was stored")

    thumbnail = make_thumbnail(image, get_settings().thumbnail_max_px)

    storage = get_storage()
    file_key = object_key(schema, "asset", content_type)
    thumbnail_key = object_key(schema, "thumbnail", "image/jpeg")
    storage.put_object(file_key, data, content_type)
    storage.put_object(thumbnail_key, thumbnail, "image/jpeg")

    asset = Asset(
        subject_id=subject_id,
        file_key=file_key,
        thumbnail_key=thumbnail_key,
        file_name=file_name,
        content_type=content_type,
        size_bytes=len(data),
        status=AssetStatus.pending,
    )
    session.add(asset)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="asset.uploaded",
        entity_type="asset",
        entity_id=str(asset.id),
    )
    _enqueue_fingerprint(session, workspace_id, asset.id)
    # In eager (test) mode the task has already run; reload so the response reflects it
    # (expire_on_commit is off, so the in-memory object would otherwise be stale).
    session.refresh(asset)
    return asset


def delete_asset(
    session: Session, *, workspace_id: int, actor_staff_id: int | None, asset: Asset
) -> None:
    """Delete an asset. NOTE: this finalizes (commits) the request transaction."""
    if not can_delete_asset(session, asset):
        raise AssetDeletionBlocked("asset is referenced and cannot be deleted")
    file_key, thumbnail_key, asset_id = asset.file_key, asset.thumbnail_key, asset.id
    session.delete(asset)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="asset.deleted",
        entity_type="asset",
        entity_id=str(asset_id),
    )
    # Commit the DB decision first; storage deletes follow, so a storage failure only leaves
    # harmless orphaned blobs rather than a row pointing at missing objects.
    session.commit()
    storage = get_storage()
    storage.delete_object(file_key)
    storage.delete_object(thumbnail_key)


def retry_asset(
    session: Session, *, workspace_id: int, actor_staff_id: int | None, asset: Asset
) -> bool:
    """Re-enqueue a failed asset, unless it has hit the attempt cap. Returns True if requeued."""
    if asset.status != AssetStatus.failed:
        return False
    if asset.attempts >= get_settings().asset_max_fingerprint_attempts:
        return False
    asset.status = AssetStatus.pending
    asset.error = None
    session.flush()
    _enqueue_fingerprint(session, workspace_id, asset.id)
    session.refresh(asset)  # reflect the eager task result in the response
    return True


def _enqueue_fingerprint(session: Session, workspace_id: int, asset_id: int) -> None:
    """Commit the pending asset, then enqueue fingerprinting.

    IMPORTANT: this COMMITS the request transaction — the worker runs in a separate
    transaction and must see the committed row to claim it (and in eager test mode .delay()
    runs inline). So `create_asset`/`retry_asset` finalize the transaction; callers must not
    perform further mutations after them.
    """
    session.commit()
    from worker.tasks import fingerprint_asset

    fingerprint_asset.delay(workspace_id, asset_id)


def requeue_pending_assets(session: Session, *, workspace_id: int) -> int:
    """Re-enqueue fingerprinting for every asset stuck in 'pending' (e.g. after a worker that
    never consumed them). Returns the count. fingerprint_asset atomically claims pending→
    processing, so re-queuing an already-running one is a harmless no-op ('skipped')."""
    from worker.tasks import fingerprint_asset

    ids = list(
        session.scalars(
            select(Asset.id).where(Asset.status == AssetStatus.pending).order_by(Asset.id)
        ).all()
    )
    for asset_id in ids:
        fingerprint_asset.delay(workspace_id, asset_id)
    return len(ids)


def reprocess_assets(
    session: Session, *, workspace_id: int, subject_id: int | None = None
) -> int:
    """Re-derive thumbnail/pHash/embedding for already-processed ('ready') assets — optionally a
    single subject — to backfill a pipeline change such as the EXIF-orientation fix. Returns the
    count enqueued."""
    from worker.tasks import reprocess_asset

    stmt = select(Asset.id).where(Asset.status == AssetStatus.ready)
    if subject_id is not None:
        stmt = stmt.where(Asset.subject_id == subject_id)
    ids = list(session.scalars(stmt.order_by(Asset.id)).all())
    for asset_id in ids:
        reprocess_asset.delay(workspace_id, asset_id)
    return len(ids)


def queue_embeddings_for_subject(
    session: Session, *, workspace_id: int, subject_id: int
) -> int:
    """Enqueue CLIP embedding for a subject's ready assets that don't have one yet — called when
    biometric consent is granted (CLAUDE.md #1). The task re-checks consent before storing, so
    it's safe even if consent is revoked before it runs. Returns the count enqueued."""
    from worker.tasks import embed_asset

    ids = list(
        session.scalars(
            select(Asset.id)
            .where(
                Asset.subject_id == subject_id,
                Asset.status == AssetStatus.ready,
                Asset.embedding.is_(None),
            )
            .order_by(Asset.id)
        ).all()
    )
    for asset_id in ids:
        embed_asset.delay(workspace_id, asset_id)
    return len(ids)
