"""Helpers for Slice 5 review tests: build scored candidates, assets and cases directly."""

from __future__ import annotations

from datetime import date

from api.app.db.session import tenant_session
from api.app.models.assets import Asset, AssetStatus
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    ReviewStatus,
)
from api.app.models.review import Case, CaseStatus
from api.app.models.rights import AgentAuthorization, ConsentRecord, ConsentType, RecordStatus
from api.app.models.subjects import AllowlistEntry, AllowlistKind, Subject
from api.app.services.discovery import _source_key, canonicalize_url

EMBEDDING_DIM = 512


def _vec(seed: float) -> list[float]:
    return [seed] * EMBEDDING_DIM


def make_subject(
    schema: str, *, authorized: bool = True, enforcement_consent: bool = False
) -> int:
    """Create a subject; optionally enforceable and with active enforcement consent (which
    makes the `likeness` claim supported)."""
    with tenant_session(schema) as session:
        subject = Subject(legal_name="Review Subject")
        session.add(subject)
        session.flush()
        if authorized:
            session.add(
                AgentAuthorization(
                    subject_id=None, signer_name="agent", authorized_date=date.today()
                )
            )
        if enforcement_consent:
            session.add(
                ConsentRecord(
                    subject_id=subject.id,
                    type=ConsentType.enforcement,
                    file_key="k",
                    file_name="c.pdf",
                    content_type="application/pdf",
                    signer_name="signer",
                    signed_date=date.today(),
                    status=RecordStatus.active,
                )
            )
        return subject.id


def add_asset(
    schema: str, subject_id: int, *, phash: str | None = None, embed: float | None = None
) -> int:
    with tenant_session(schema) as session:
        asset = Asset(
            subject_id=subject_id,
            file_key="asset-key",
            thumbnail_key="asset-thumb",
            file_name="a.png",
            content_type="image/png",
            size_bytes=1,
            status=AssetStatus.ready,
            phash=phash,
            embedding=_vec(embed) if embed is not None else None,
        )
        session.add(asset)
        session.flush()
        return asset.id


def add_candidate(
    schema: str,
    subject_id: int,
    *,
    source_url: str = "https://found.example/x.jpg",
    page_url: str | None = None,
    kind: CandidateKind = CandidateKind.image,
    phash: str | None = None,
    embed: float | None = None,
    title: str | None = None,
    thumbnail_key: str | None = "cand-thumb",
    score: int | None = 50,
    review_status: ReviewStatus = ReviewStatus.pending,
    best_match_asset_id: int | None = None,
) -> int:
    canonical = canonicalize_url(source_url) or source_url
    with tenant_session(schema) as session:
        candidate = DiscoveryCandidate(
            subject_id=subject_id,
            provider="fake",
            kind=kind,
            source_url=canonical,
            source_key=_source_key(canonical),
            page_url=page_url,
            title=title,
            phash=phash,
            embedding=_vec(embed) if embed is not None else None,
            thumbnail_key=thumbnail_key if kind == CandidateKind.image else None,
            content_type="image/jpeg" if kind == CandidateKind.image else None,
            score=score,
            review_status=review_status,
            best_match_asset_id=best_match_asset_id,
        )
        session.add(candidate)
        session.flush()
        return candidate.id


def add_allowlist(schema: str, kind: AllowlistKind, value: str) -> None:
    with tenant_session(schema) as session:
        session.add(AllowlistEntry(kind=kind, value=value))


def add_confirmed_case(
    schema: str, subject_id: int, *, candidate_id: int, matched_asset_id: int | None
) -> int:
    with tenant_session(schema) as session:
        case = Case(
            subject_id=subject_id,
            candidate_id=candidate_id,
            matched_asset_id=matched_asset_id,
            claim_type="likeness",
            status=CaseStatus.confirmed,
        )
        session.add(case)
        session.flush()
        return case.id
