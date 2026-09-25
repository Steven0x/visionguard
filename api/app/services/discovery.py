"""Discovery services: URL canonicalization, the auth gate, budget, intake, candidates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.config import get_settings
from api.app.fingerprint.embedder import get_embedder
from api.app.fingerprint.hashing import phash_hex, sha256_hex
from api.app.images import InvalidImage, make_thumbnail, validate_and_load
from api.app.models.discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    DiscoverySettings,
    RunKind,
    RunStatus,
)
from api.app.models.subjects import Subject
from api.app.net.fetcher import Fetcher, get_fetcher
from api.app.net.ssrf import SsrfError
from api.app.services.claim_support import subject_enforcement
from api.app.services.scoring import apply_scoring
from api.app.storage import get_storage
from api.app.storage.keys import object_key

_TRACKING_KEYS = {
    "gclid", "fbclid", "mc_eid", "mc_cid", "igshid", "yclid", "ref_src", "_ga",
}


class DiscoveryNotAuthorized(Exception):
    """Raised when discovery is attempted for a subject without active authorization."""


class CsamScannerRequired(Exception):
    """Raised when found-image storage is attempted without a configured CSAM scanner."""


def csam_scanning_ready() -> bool:
    """Fail closed: storing images fetched from the open web (real 'safe' fetcher) is only
    allowed once a CSAM scanner is configured. The fake fetcher (tests/CI) is exempt."""
    settings = get_settings()
    return settings.fetcher_backend == "fake" or settings.csam_scanner_enabled


# ── URL canonicalization ──────────────────────────────────────────────────────


def canonicalize_url(url: str) -> str | None:
    """Normalize scheme/host/port, strip tracking params + fragment. None if not http(s)."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    default_port = 443 if scheme == "https" else 80
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_KEYS)
    )
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(query), ""))


def _source_key(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode()).hexdigest()


def _safe_page_url(page_url: str | None) -> str | None:
    """Only keep http(s) page URLs (drops javascript:/data: from provider results)."""
    return canonicalize_url(page_url) if page_url else None


# ── Gate / settings / budget ──────────────────────────────────────────────────


def assert_enforceable(session: Session, subject: Subject) -> None:
    if not subject_enforcement(session, subject)["enforceable"]:
        raise DiscoveryNotAuthorized(
            "discovery requires an active agent authorization for this subject"
        )


def get_or_create_settings(session: Session) -> DiscoverySettings:
    # Fixed id=1 makes the PK the single-row guarantee; a concurrent double-insert loses to
    # the PK and re-reads the winner (via a savepoint so the outer transaction survives).
    settings = session.get(DiscoverySettings, 1)
    if settings is None:
        settings = DiscoverySettings(
            id=1, monthly_call_budget=get_settings().discovery_default_monthly_budget
        )
        session.add(settings)
        try:
            with session.begin_nested():
                session.flush()
        except IntegrityError:
            settings = session.get(DiscoverySettings, 1)
    if settings is None:  # pragma: no cover - always present after insert/reselect
        raise RuntimeError("discovery settings row missing")
    return settings


def month_to_date_calls(session: Session) -> int:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(
        select(func.coalesce(func.sum(DiscoveryRun.calls_made), 0)).where(
            DiscoveryRun.started_at >= month_start
        )
    )
    return int(total or 0)


def budget_remaining(session: Session, settings: DiscoverySettings) -> int:
    return max(0, settings.monthly_call_budget - month_to_date_calls(session))


# ── Runs ──────────────────────────────────────────────────────────────────────


def start_run(
    session: Session,
    *,
    kind: RunKind,
    subject_id: int,
    provider: str | None = None,
    asset_id: int | None = None,
    query: str | None = None,
) -> DiscoveryRun:
    run = DiscoveryRun(
        kind=kind,
        provider=provider,
        subject_id=subject_id,
        asset_id=asset_id,
        query=query,
        status=RunStatus.running,
    )
    session.add(run)
    session.flush()
    return run


def finish_run(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    run: DiscoveryRun,
    status: RunStatus,
    calls_made: int = 0,
    cost_cents: int = 0,
    candidates_found: int = 0,
    error: str | None = None,
) -> None:
    run.status = status
    run.calls_made = calls_made
    run.estimated_cost_cents = cost_cents
    run.candidates_found = candidates_found
    run.error = error
    run.finished_at = datetime.now(UTC)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="discovery.scan_run" if run.kind != RunKind.manual_intake else "discovery.intake",
        entity_type="discovery_run",
        entity_id=str(run.id),
        meta={
            "kind": str(run.kind),
            "provider": run.provider,
            "status": str(status),
            "calls_made": calls_made,
            "cost_cents": cost_cents,
            "candidates_found": candidates_found,
        },
    )


# ── Intake ────────────────────────────────────────────────────────────────────


def intake_urls(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    subject: Subject,
    urls: list[str],
) -> DiscoveryRun:
    assert_enforceable(session, subject)
    if len(urls) > get_settings().discovery_intake_max_urls:
        raise ValueError(
            f"too many URLs (max {get_settings().discovery_intake_max_urls} per batch)"
        )

    run = start_run(session, kind=RunKind.manual_intake, subject_id=subject.id, provider="manual")
    seen: set[str] = set()
    inserted = 0
    for raw in urls:
        canonical = canonicalize_url(raw)
        if canonical is None:
            continue
        key = _source_key(canonical)
        if key in seen:
            continue
        seen.add(key)
        if _candidate_exists(session, subject.id, key):
            continue
        candidate = DiscoveryCandidate(
            subject_id=subject.id,
            run_id=run.id,
            provider="manual",
            kind=CandidateKind.link,
            source_url=canonical,
            source_key=key,
            page_url=canonical,
        )
        session.add(candidate)
        session.flush()
        apply_scoring(session, candidate)  # score + allowlist routing before the inbox
        inserted += 1
    finish_run(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        run=run,
        status=RunStatus.completed,
        candidates_found=inserted,
    )
    return run


# ── Candidates ────────────────────────────────────────────────────────────────


def _candidate_exists(session: Session, subject_id: int, source_key: str) -> bool:
    return (
        session.scalar(
            select(DiscoveryCandidate.id).where(
                DiscoveryCandidate.subject_id == subject_id,
                DiscoveryCandidate.source_key == source_key,
            )
        )
        is not None
    )


def add_image_candidate(
    session: Session,
    *,
    schema: str,
    subject_id: int,
    run_id: int,
    provider: str,
    query: str | None,
    source_url: str,
    page_url: str | None,
    title: str | None = None,
    fetcher: Fetcher | None = None,
) -> DiscoveryCandidate | None:
    """Fetch a found image through the safe fetcher and store fingerprints + a thumbnail.

    Returns None if the URL is a duplicate, unsafe to fetch, or not a valid image. We never
    store the full-resolution file — only fingerprints and a small thumbnail.
    """
    canonical = canonicalize_url(source_url)
    if canonical is None:
        return None
    key = _source_key(canonical)
    if _candidate_exists(session, subject_id, key):
        return None

    # CSAM scan choke point (CLAUDE.md #7). This is the single place found imagery enters
    # storage. Until a PhotoDNA-style scanner is wired here (hit → NCMEC path, never stored),
    # storing images fetched from the open web is refused — enforced in code, not just docs.
    if not csam_scanning_ready():
        raise CsamScannerRequired(
            "storing found images requires a configured CSAM scanner"
        )

    fetcher = fetcher or get_fetcher()
    try:
        result = fetcher.fetch(canonical)
    except SsrfError:
        return None  # skip unsafe targets, don't fail the run
    if not result.content_type.startswith("image/"):
        return None
    try:
        image = validate_and_load(result.content)
    except InvalidImage:
        return None

    thumbnail = make_thumbnail(image, get_settings().thumbnail_max_px)
    thumbnail_key = object_key(schema, "candidate_thumbnail", "image/jpeg")
    get_storage().put_object(thumbnail_key, thumbnail, "image/jpeg")

    candidate = DiscoveryCandidate(
        subject_id=subject_id,
        run_id=run_id,
        provider=provider,
        query=query,
        kind=CandidateKind.image,
        source_url=canonical,
        source_key=key,
        page_url=_safe_page_url(page_url),
        title=title,
        sha256=sha256_hex(result.content),
        phash=phash_hex(image),
        embedding=get_embedder().embed(result.content),
        thumbnail_key=thumbnail_key,
        content_type=result.content_type,
    )
    session.add(candidate)
    session.flush()
    apply_scoring(session, candidate)  # score + allowlist routing before the inbox
    return candidate


def add_link_candidate(
    session: Session,
    *,
    subject_id: int,
    run_id: int,
    provider: str,
    query: str | None,
    source_url: str,
    page_url: str | None,
    title: str | None = None,
) -> DiscoveryCandidate | None:
    canonical = canonicalize_url(source_url)
    if canonical is None:
        return None
    key = _source_key(canonical)
    if _candidate_exists(session, subject_id, key):
        return None
    candidate = DiscoveryCandidate(
        subject_id=subject_id,
        run_id=run_id,
        provider=provider,
        query=query,
        kind=CandidateKind.link,
        source_url=canonical,
        source_key=key,
        page_url=_safe_page_url(page_url),
        title=title,
    )
    session.add(candidate)
    session.flush()
    apply_scoring(session, candidate)  # score + allowlist routing before the inbox
    return candidate


def list_candidates(session: Session, subject_id: int) -> list[DiscoveryCandidate]:
    return list(
        session.scalars(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.subject_id == subject_id)
            .order_by(DiscoveryCandidate.discovered_at.desc(), DiscoveryCandidate.id.desc())
        ).all()
    )


def get_candidate(session: Session, candidate_id: int) -> DiscoveryCandidate | None:
    return session.get(DiscoveryCandidate, candidate_id)


def list_runs(session: Session, subject_id: int) -> list[DiscoveryRun]:
    return list(
        session.scalars(
            select(DiscoveryRun)
            .where(DiscoveryRun.subject_id == subject_id)
            .order_by(DiscoveryRun.started_at.desc(), DiscoveryRun.id.desc())
        ).all()
    )
