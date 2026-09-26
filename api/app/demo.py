"""Seed a clickable local demo: one workspace, an authorized+consenting subject, five
fingerprinted sample images, and a discovery run (fake providers) so the review inbox has
items. Idempotent — safe to re-run (candidates dedupe on their source key).

Runs everything in-process (no Celery/worker needed) and uses whatever STORAGE_BACKEND /
EMBEDDER_BACKEND / PROVIDER_BACKEND the environment selects. For a demo you want a SHARED
object store (MinIO, STORAGE_BACKEND=s3) so thumbnails written here are visible to the API
server — the in-memory "fake" store is per-process and won't be.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

from PIL import Image, ImageDraw
from sqlalchemy import func, select

from api.app.db.session import public_session, tenant_session
from api.app.fingerprint.embedder import get_embedder
from api.app.fingerprint.hashing import phash_hex, sha256_hex
from api.app.images import make_thumbnail, validate_and_load
from api.app.models.assets import Asset, AssetStatus, SubjectKeyword
from api.app.models.public import Workspace
from api.app.models.rights import (
    AgentAuthorization,
    ConsentRecord,
    ConsentType,
    RecordStatus,
)
from api.app.models.subjects import AllowlistEntry, AllowlistKind, Subject
from api.app.services import discovery as discovery_svc
from api.app.services.provisioning import create_workspace
from api.app.storage import get_storage
from api.app.storage.keys import object_key

_SLUG = "demo-agency"
_SUBJECT_NAME = "Demo Subject"
_N_IMAGES = 5


@dataclass
class DemoResult:
    workspace_id: int
    workspace_slug: str
    schema: str
    subject_id: int
    assets: int
    pending_candidates: int
    auto_dismissed: int


def _make_png(seed: int) -> bytes:
    """A small, distinct PNG per seed so the five assets have different fingerprints."""
    img = Image.new("RGB", (256, 256), ((seed * 47) % 256, (seed * 91) % 256, (seed * 29) % 256))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40 + seed * 8, 40, 200, 120 + seed * 12], fill=(20, 20, 20))
    draw.ellipse([60, 140, 180 + seed * 6, 230], fill=((seed * 130) % 256, 200, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _get_or_create_workspace() -> Workspace:
    with public_session() as session:
        existing = session.scalar(select(Workspace).where(Workspace.slug == _SLUG))
        if existing is not None:
            session.expunge(existing)
            return existing
    return create_workspace(name="Demo Agency", slug=_SLUG, plan="starter")


def _ensure_subject(schema: str) -> int:
    with tenant_session(schema) as session:
        subject = session.scalar(select(Subject).where(Subject.legal_name == _SUBJECT_NAME))
        if subject is None:
            subject = Subject(
                legal_name=_SUBJECT_NAME,
                stage_names=["Demo Star"],
                handles=["@demostar"],
            )
            session.add(subject)
            session.flush()
        subject_id = subject.id

        # Active workspace-level authorization → the subject is enforceable.
        has_auth = session.scalar(
            select(AgentAuthorization.id).where(
                AgentAuthorization.status == RecordStatus.active
            )
        )
        if has_auth is None:
            session.add(
                AgentAuthorization(
                    subject_id=None, signer_name="Demo Agency", authorized_date=date.today()
                )
            )
        # Active enforcement consent → the likeness claim is supported.
        has_consent = session.scalar(
            select(ConsentRecord.id).where(
                ConsentRecord.subject_id == subject_id,
                ConsentRecord.type == ConsentType.enforcement,
                ConsentRecord.status == RecordStatus.active,
            )
        )
        if has_consent is None:
            session.add(
                ConsentRecord(
                    subject_id=subject_id,
                    type=ConsentType.enforcement,
                    file_key="demo/consent.pdf",
                    file_name="consent.pdf",
                    content_type="application/pdf",
                    signer_name=_SUBJECT_NAME,
                    signed_date=date.today(),
                    status=RecordStatus.active,
                )
            )
        for kw in ("demo star leaked", "demostar free"):
            if session.scalar(
                select(SubjectKeyword.id).where(
                    SubjectKeyword.subject_id == subject_id, SubjectKeyword.keyword == kw
                )
            ) is None:
                session.add(SubjectKeyword(subject_id=subject_id, keyword=kw))
        return subject_id


def _ensure_assets(schema: str, subject_id: int) -> int:
    storage = get_storage()
    with tenant_session(schema) as session:
        have = int(
            session.scalar(
                select(func.count()).select_from(Asset).where(Asset.subject_id == subject_id)
            )
            or 0
        )
    embedder = get_embedder()
    created = 0
    for i in range(have, _N_IMAGES):
        data = _make_png(i + 1)
        image = validate_and_load(data)
        thumbnail = make_thumbnail(image, 256)
        file_key = object_key(schema, "asset", "image/png")
        thumb_key = object_key(schema, "thumbnail", "image/jpeg")
        storage.put_object(file_key, data, "image/png")
        storage.put_object(thumb_key, thumbnail, "image/jpeg")
        with tenant_session(schema) as session:
            session.add(
                Asset(
                    subject_id=subject_id,
                    file_key=file_key,
                    thumbnail_key=thumb_key,
                    file_name=f"demo-{i + 1}.png",
                    content_type="image/png",
                    size_bytes=len(data),
                    status=AssetStatus.ready,
                    sha256=sha256_hex(data),
                    phash=phash_hex(image),
                    embedding=embedder.embed(data),
                )
            )
        created += 1
    return max(created, _N_IMAGES)


def _run_discovery(workspace_id: int, schema: str, subject_id: int) -> None:
    # Call the Celery task bodies directly (synchronous, no broker/worker needed).
    from worker.discovery import keyword_scan, reverse_image_scan

    with tenant_session(schema) as session:
        asset_ids = list(
            session.scalars(
                select(Asset.id).where(
                    Asset.subject_id == subject_id, Asset.status == AssetStatus.ready
                )
            ).all()
        )
    for asset_id in asset_ids:
        reverse_image_scan(workspace_id, subject_id, asset_id)
    keyword_scan(workspace_id, subject_id)

    # Manual intake: a couple of pasted URLs (one on a leak domain → higher rule score).
    with tenant_session(schema) as session:
        subject = session.get(Subject, subject_id)
        assert subject is not None  # noqa: S101 - just ensured above
        discovery_svc.intake_urls(
            session,
            workspace_id=workspace_id,
            actor_staff_id=None,
            subject=subject,
            urls=[
                "https://leaks.example/demostar/gallery",
                "https://randomblog.example/post/demo-star",
            ],
        )

    # Show the allowlist path: add a licensee, then intake a URL on it → auto-dismissed.
    with tenant_session(schema) as session:
        if session.scalar(
            select(AllowlistEntry.id).where(AllowlistEntry.value == "licensee.example")
        ) is None:
            session.add(AllowlistEntry(kind=AllowlistKind.domain, value="licensee.example"))
    with tenant_session(schema) as session:
        subject = session.get(Subject, subject_id)
        assert subject is not None  # noqa: S101
        discovery_svc.intake_urls(
            session,
            workspace_id=workspace_id,
            actor_staff_id=None,
            subject=subject,
            urls=["https://licensee.example/authorized/demostar"],
        )


def _counts(schema: str, subject_id: int) -> tuple[int, int]:
    from api.app.models.discovery import DiscoveryCandidate, ReviewStatus

    with tenant_session(schema) as session:
        pending = int(
            session.scalar(
                select(func.count())
                .select_from(DiscoveryCandidate)
                .where(DiscoveryCandidate.review_status == ReviewStatus.pending)
            )
            or 0
        )
        auto = int(
            session.scalar(
                select(func.count())
                .select_from(DiscoveryCandidate)
                .where(DiscoveryCandidate.review_status == ReviewStatus.auto_dismissed)
            )
            or 0
        )
    return pending, auto


def seed_demo() -> DemoResult:
    """Idempotently seed the demo workspace + subject + assets + discovery candidates."""
    from api.app.storage.evidence import get_evidence_storage

    get_storage().ensure_bucket()
    get_evidence_storage().ensure_bucket()  # write-once evidence bucket (used on confirm)
    workspace = _get_or_create_workspace()
    schema = workspace.schema_name
    subject_id = _ensure_subject(schema)
    assets = _ensure_assets(schema, subject_id)
    _run_discovery(workspace.id, schema, subject_id)
    pending, auto = _counts(schema, subject_id)
    return DemoResult(
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        schema=schema,
        subject_id=subject_id,
        assets=assets,
        pending_candidates=pending,
        auto_dismissed=auto,
    )
