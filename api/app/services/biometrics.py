"""Biometric data purge hook (CLAUDE.md #1).

Face templates/embeddings arrive in a later slice; this hook is wired now so that revoking a
biometric consent hard-deletes them the moment they exist. Today it deletes nothing.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def purge_biometric_data(session: Session, subject_id: int) -> int:
    """Hard-delete all biometric templates/embeddings for a subject. Returns the count.

    No face tables exist yet, so this returns 0. When they land, delete them here (within the
    same tenant session) and keep the return count for the audit record.
    """
    # Future: DELETE FROM face_templates / face_embeddings WHERE subject_id = :subject_id.
    _ = (session, subject_id)
    return 0
