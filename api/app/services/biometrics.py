"""Biometric data purge hook (CLAUDE.md #1).

Revoking a subject's last active biometric consent must hard-delete their biometric data. Until
counsel rules otherwise, we treat whole-image CLIP embeddings of people's photos as biometric
(see docs/legal/claims-matrix.md), so this nulls the `embedding` column for the subject's assets.
Face templates/embeddings (a later slice) delete here too when they land.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from api.app.models.assets import Asset


def purge_biometric_data(session: Session, subject_id: int) -> int:
    """Hard-delete all biometric data for a subject, in the caller's tenant session. Returns the
    number of assets whose embedding was cleared (used for the audit record)."""
    result = session.execute(
        update(Asset)
        .where(Asset.subject_id == subject_id, Asset.embedding.is_not(None))
        .values(embedding=None)
    )
    # Future: also DELETE FROM face_templates / face_embeddings WHERE subject_id = :subject_id.
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
