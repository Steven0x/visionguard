"""One-time cleanup: null CLIP embeddings for subjects without biometric consent (CLAUDE.md #1)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.assets import EMBEDDING_DIM, Asset, AssetStatus
from api.app.models.audit import AuditLog
from api.app.models.discovery import CandidateKind, DiscoveryCandidate
from api.app.models.rights import ConsentRecord, ConsentType, RecordStatus
from api.app.models.subjects import Subject
from api.app.services.biometrics import purge_unconsented_embeddings


def _asset(subject_id: int) -> Asset:
    return Asset(
        subject_id=subject_id, file_key="k", thumbnail_key="t", file_name="a.png",
        content_type="image/png", size_bytes=1, status=AssetStatus.ready,
        embedding=[0.1] * EMBEDDING_DIM,
    )


def _candidate(subject_id: int, key: str) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        subject_id=subject_id, run_id=None, provider="x", kind=CandidateKind.image,
        source_url=f"https://found.example/{key}.png", source_key=key,
        embedding=[0.2] * EMBEDDING_DIM,
    )


def _setup(schema: str) -> tuple[int, int]:
    """One unconsented subject (asset + candidate embeddings) and one consented one (asset)."""
    with tenant_session(schema) as s:
        unconsented = Subject(legal_name="no-consent")  # biometrics_blocked defaults True
        consented = Subject(legal_name="consented", biometrics_blocked=False)
        s.add_all([unconsented, consented])
        s.flush()
        s.add_all([
            _asset(unconsented.id),
            _candidate(unconsented.id, "u1"),
            _asset(consented.id),
            ConsentRecord(
                subject_id=consented.id, type=ConsentType.biometric, file_key="k",
                file_name="c.pdf", content_type="application/pdf", signer_name="x",
                signed_date=date(2026, 1, 1), status=RecordStatus.active,
            ),
        ])
        s.flush()
        return unconsented.id, consented.id


def test_dry_run_counts_but_changes_nothing(db, new_workspace) -> None:
    schema = new_workspace.schema_name
    unconsented_id, _ = _setup(schema)

    with tenant_session(schema) as s:
        affected = purge_unconsented_embeddings(
            s, workspace_id=new_workspace.id, actor_staff_id=None, dry_run=True
        )
    assert affected == {unconsented_id: 2}  # one asset + one candidate

    with tenant_session(schema) as s:  # nothing nulled, no audit written
        asset = s.scalar(select(Asset).where(Asset.subject_id == unconsented_id))
        assert asset is not None and asset.embedding is not None
        assert "biometrics.purged" not in set(s.scalars(select(AuditLog.action)).all())


def test_real_run_purges_only_unconsented_and_audits(db, new_workspace) -> None:
    schema = new_workspace.schema_name
    unconsented_id, consented_id = _setup(schema)

    with tenant_session(schema) as s:
        affected = purge_unconsented_embeddings(
            s, workspace_id=new_workspace.id, actor_staff_id=None, dry_run=False
        )
    assert affected == {unconsented_id: 2}

    with tenant_session(schema) as s:
        # Unconsented subject: both embeddings cleared.
        for asset in s.scalars(select(Asset).where(Asset.subject_id == unconsented_id)):
            assert asset.embedding is None
        for candidate in s.scalars(
            select(DiscoveryCandidate).where(DiscoveryCandidate.subject_id == unconsented_id)
        ):
            assert candidate.embedding is None
        # Consented subject: embedding preserved.
        kept = s.scalar(select(Asset).where(Asset.subject_id == consented_id))
        assert kept is not None and kept.embedding is not None
        # One audit per affected subject.
        purges = [a for a in s.scalars(select(AuditLog)).all() if a.action == "biometrics.purged"]
        assert len(purges) == 1
        assert purges[0].entity_id == str(unconsented_id)
        assert purges[0].meta is not None
        assert purges[0].meta["reason"] == "cleanup_unconsented"
