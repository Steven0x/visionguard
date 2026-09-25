"""Helpers for discovery tests: build authorized/unauthorized subjects in a schema."""

from __future__ import annotations

from datetime import date

from api.app.db.session import tenant_session
from api.app.models.assets import Asset, AssetStatus, SubjectKeyword
from api.app.models.rights import AgentAuthorization
from api.app.models.subjects import Subject


def _add_ready_asset(session, subject_id: int) -> int:
    asset = Asset(
        subject_id=subject_id,
        file_key="orig-key",
        thumbnail_key="thumb-key",
        file_name="a.png",
        content_type="image/png",
        size_bytes=1,
        status=AssetStatus.ready,
    )
    session.add(asset)
    session.flush()
    return asset.id


def authorized_subject(
    schema: str,
    *,
    ready_asset: bool = False,
    stage_names: tuple[str, ...] = (),
    handles: tuple[str, ...] = (),
    keywords: tuple[str, ...] = (),
) -> tuple[int, int | None]:
    with tenant_session(schema) as session:
        subject = Subject(
            legal_name="Auth Subject",
            stage_names=list(stage_names),
            handles=list(handles),
        )
        session.add(subject)
        session.flush()
        # A workspace-level active authorization makes the subject enforceable.
        session.add(
            AgentAuthorization(
                subject_id=None, signer_name="agent", authorized_date=date.today()
            )
        )
        for keyword in keywords:
            session.add(SubjectKeyword(subject_id=subject.id, keyword=keyword))
        asset_id = _add_ready_asset(session, subject.id) if ready_asset else None
        return subject.id, asset_id


def unauthorized_subject(
    schema: str, *, ready_asset: bool = False
) -> tuple[int, int | None]:
    with tenant_session(schema) as session:
        subject = Subject(legal_name="Unauth Subject")
        session.add(subject)
        session.flush()
        asset_id = _add_ready_asset(session, subject.id) if ready_asset else None
        return subject.id, asset_id
