"""Biometric data purge hook (CLAUDE.md #1).

Revoking a subject's last active biometric consent must hard-delete their biometric data. Until
counsel rules otherwise, we treat whole-image CLIP embeddings of people's photos as biometric
(see docs/legal/claims-matrix.md), so this nulls the `embedding` column for the subject's assets.
Face templates/embeddings (a later slice) delete here too when they land.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.models.assets import Asset
from api.app.models.discovery import DiscoveryCandidate

# The tables that hold a subject-associated CLIP embedding (treated as biometric, CLAUDE.md #1).
_EMBEDDING_MODELS = (Asset, DiscoveryCandidate)


def purge_biometric_data(session: Session, subject_id: int) -> int:
    """Hard-delete all biometric data for a subject, in the caller's tenant session. Returns the
    total number of embeddings cleared (used for the audit record).

    Nulls both the subject's reference-asset embeddings AND the embeddings of every discovery
    candidate (found image) for that subject — both are subject-associated biometric data."""
    cleared = 0
    for model in _EMBEDDING_MODELS:
        result = session.execute(
            update(model)
            .where(model.subject_id == subject_id, model.embedding.is_not(None))
            .values(embedding=None)
        )
        cleared += int(result.rowcount or 0)  # type: ignore[attr-defined]
    # Future: also DELETE FROM face_templates / face_embeddings WHERE subject_id = :subject_id.
    return cleared


def _count_embeddings(session: Session, subject_id: int) -> int:
    total = 0
    for model in _EMBEDDING_MODELS:
        total += int(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.subject_id == subject_id, model.embedding.is_not(None))
            )
            or 0
        )
    return total


def _subjects_with_embeddings(session: Session) -> list[int]:
    ids: set[int] = set()
    for model in _EMBEDDING_MODELS:
        ids.update(
            session.scalars(
                select(model.subject_id).where(model.embedding.is_not(None)).distinct()
            ).all()
        )
    return sorted(ids)


def purge_unconsented_embeddings(
    session: Session, *, workspace_id: int, actor_staff_id: int | None, dry_run: bool
) -> dict[int, int]:
    """One-time cleanup (CLAUDE.md #1): null the CLIP embeddings of every subject in this tenant
    that lacks active biometric consent OR is geo-blocked (biometrics_blocked). Returns a
    ``{subject_id: embeddings_cleared}`` map for the affected subjects. Writes one
    ``biometrics.purged`` audit per affected subject unless ``dry_run``."""
    # Imported here to avoid a module import cycle (claim_support ← nothing in biometrics).
    from api.app.services.claim_support import biometric_features_enabled

    affected: dict[int, int] = {}
    for subject_id in _subjects_with_embeddings(session):
        if biometric_features_enabled(session, subject_id):
            continue  # consented + unblocked → keep
        count = _count_embeddings(session, subject_id)
        if count == 0:
            continue
        affected[subject_id] = count
        if not dry_run:
            purge_biometric_data(session, subject_id)
            record_audit(
                session,
                workspace_id=workspace_id,
                actor_staff_id=actor_staff_id,
                action="biometrics.purged",
                entity_type="subject",
                entity_id=str(subject_id),
                meta={"deleted": count, "reason": "cleanup_unconsented"},
            )
    return affected
