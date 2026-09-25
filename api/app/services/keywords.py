"""Subject keyword (text identifier) services."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.models.assets import SubjectKeyword
from api.app.models.subjects import Subject
from api.app.services.subjects import normalize_handles


def normalize_keyword(keyword: str) -> str:
    return re.sub(r"\s+", " ", keyword).strip().lower()


def list_keywords(session: Session, subject_id: int) -> list[SubjectKeyword]:
    return list(
        session.scalars(
            select(SubjectKeyword)
            .where(SubjectKeyword.subject_id == subject_id)
            .order_by(SubjectKeyword.keyword)
        ).all()
    )


def add_keyword(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    subject_id: int,
    keyword: str,
) -> SubjectKeyword:
    normalized = normalize_keyword(keyword)
    if not normalized:
        raise ValueError("keyword is required")
    existing = session.scalar(
        select(SubjectKeyword).where(
            SubjectKeyword.subject_id == subject_id,
            SubjectKeyword.keyword == normalized,
        )
    )
    if existing is not None:
        return existing
    record = SubjectKeyword(subject_id=subject_id, keyword=normalized)
    session.add(record)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="keyword.added",
        entity_type="subject_keyword",
        entity_id=str(record.id),
    )
    return record


def get_keyword(session: Session, keyword_id: int) -> SubjectKeyword | None:
    return session.get(SubjectKeyword, keyword_id)


def remove_keyword(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    record: SubjectKeyword,
) -> None:
    keyword_id = record.id
    session.delete(record)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="keyword.removed",
        entity_type="subject_keyword",
        entity_id=str(keyword_id),
    )


def identifiers(session: Session, subject: Subject) -> list[str]:
    """Union of the subject's stage names, normalized handles, and keywords."""
    values: list[str] = []
    seen: set[str] = set()
    for group in (
        subject.stage_names,
        normalize_handles(subject.handles),
        [k.keyword for k in list_keywords(session, subject.id)],
    ):
        for value in group:
            if value not in seen:
                seen.add(value)
                values.append(value)
    return values
