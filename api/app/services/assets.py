"""Asset services: upload (store + thumbnail + enqueue), list, delete, retry."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.images import make_thumbnail, validate_and_load
from api.app.models.assets import Asset, AssetStatus
from api.app.storage import get_storage
from api.app.storage.keys import object_key


class AssetDeletionBlocked(Exception):
    """Raised when a guard hook forbids deleting an asset (e.g. referenced by a case)."""


def can_delete_asset(session: Session, asset: Asset) -> bool:
    """Slice 3: assets aren't referenced yet, so deletion is always allowed. Later slices
    return False when a Match/Case references the asset, so evidence can't be deleted."""
    _ = (session, asset)
    return True


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
