"""Discovery Celery jobs: reverse-image + keyword scans, scheduling, thumbnail cleanup.

Scan tasks NEVER raise (eager-safe): failures are recorded on the run. Budget is reserved
under a row lock BEFORE any provider call, so concurrent scans can't exceed the monthly cap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api.app.db.base import schema_for_workspace
from api.app.db.session import public_session, tenant_session
from api.app.models.assets import Asset, AssetStatus
from api.app.models.discovery import (
    DiscoveryCandidate,
    DiscoveryRun,
    DiscoverySettings,
    RunKind,
    RunStatus,
    ScanFrequency,
)
from api.app.models.public import Workspace
from api.app.models.subjects import Subject, SubjectStatus
from api.app.providers import get_keyword_provider, get_reverse_image_providers
from api.app.providers.base import ProviderResult
from api.app.services import discovery as svc
from api.app.services.claim_support import subject_enforcement
from api.app.services.keywords import identifiers as get_identifiers
from api.app.storage import get_storage
from sqlalchemy import select

from worker.celery_app import celery

_SIGNED_TTL = 300


def _finish(
    schema: str,
    workspace_id: int,
    run_id: int,
    *,
    status: RunStatus,
    calls_made: int = 0,
    cost_cents: int = 0,
    candidates_found: int = 0,
    error: str | None = None,
) -> None:
    with tenant_session(schema) as session:
        run = session.get(DiscoveryRun, run_id)
        if run is not None:
            svc.finish_run(
                session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                status=status, calls_made=calls_made, cost_cents=cost_cents,
                candidates_found=candidates_found, error=error,
            )


@celery.task(name="worker.reverse_image_scan")
def reverse_image_scan(workspace_id: int, subject_id: int, asset_id: int) -> str:
    schema = schema_for_workspace(workspace_id)
    # 1) Gate/budget decision + budget RESERVATION under a settings row lock (committed).
    with tenant_session(schema) as session:
        subject = session.get(Subject, subject_id)
        asset = session.get(Asset, asset_id)
        if subject is None or asset is None or asset.status != AssetStatus.ready:
            return "skipped"
        svc.get_or_create_settings(session)
        settings = session.get(DiscoverySettings, 1, with_for_update=True)
        assert settings is not None  # noqa: S101 - just created above
        budget = settings.monthly_call_budget
        tineye_enabled = settings.tineye_enabled
        run = svc.start_run(
            session, kind=RunKind.reverse_image, subject_id=subject_id, asset_id=asset_id
        )
        run_id = run.id
        if not subject_enforcement(session, subject)["enforceable"]:
            svc.finish_run(session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                           status=RunStatus.blocked)
            return "blocked"
        if not svc.csam_scanning_ready():
            svc.finish_run(session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                           status=RunStatus.blocked)
            return "blocked"
        mtd = svc.month_to_date_calls(session)
        if mtd >= budget:
            svc.finish_run(session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                           status=RunStatus.blocked)
            return "blocked"
        providers = get_reverse_image_providers(tineye_enabled=tineye_enabled)
        reserve = min(len(providers), budget - mtd)
        capped = reserve < len(providers)
        run.calls_made = reserve  # reserve budget before releasing the lock
        session.flush()
        image_url = get_storage().generate_download_url(
            asset.file_key, filename=asset.file_name, expires_in=_SIGNED_TTL
        )

    cost = candidates = 0
    try:
        collected: list[tuple[str, ProviderResult]] = []
        for provider in providers[:reserve]:
            response = provider.search(image_url)
            cost += response.cost_cents
            for result in response.results:
                collected.append((provider.name, result))
        with tenant_session(schema) as session:
            for provider_name, result in collected:
                if svc.add_image_candidate(
                    session, schema=schema, subject_id=subject_id, run_id=run_id,
                    provider=provider_name, query=None,
                    source_url=result.source_url, page_url=result.page_url,
                ) is not None:
                    candidates += 1
            final_run = session.get(DiscoveryRun, run_id)
            if final_run is not None:
                svc.finish_run(
                    session, workspace_id=workspace_id, actor_staff_id=None, run=final_run,
                    status=RunStatus.partial if capped else RunStatus.completed,
                    calls_made=reserve, cost_cents=cost, candidates_found=candidates,
                )
        return "completed"
    except Exception as exc:  # never raises — eager-safe
        _finish(schema, workspace_id, run_id, status=RunStatus.failed,
                calls_made=reserve, cost_cents=cost, candidates_found=candidates,
                error=str(exc)[:1000])
        return "failed"


@celery.task(name="worker.keyword_scan")
def keyword_scan(workspace_id: int, subject_id: int) -> str:
    schema = schema_for_workspace(workspace_id)
    with tenant_session(schema) as session:
        subject = session.get(Subject, subject_id)
        if subject is None:
            return "skipped"
        svc.get_or_create_settings(session)
        settings = session.get(DiscoverySettings, 1, with_for_update=True)
        assert settings is not None  # noqa: S101
        budget = settings.monthly_call_budget
        run = svc.start_run(
            session, kind=RunKind.keyword, subject_id=subject_id, provider="keyword"
        )
        run_id = run.id
        if not subject_enforcement(session, subject)["enforceable"]:
            svc.finish_run(session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                           status=RunStatus.blocked)
            return "blocked"
        mtd = svc.month_to_date_calls(session)
        if mtd >= budget:
            svc.finish_run(session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                           status=RunStatus.blocked)
            return "blocked"
        queries = get_identifiers(session, subject)
        reserve = min(len(queries), budget - mtd)
        capped = reserve < len(queries)
        run.calls_made = reserve
        session.flush()

    cost = candidates = 0
    try:
        provider = get_keyword_provider()
        collected: list[tuple[str, ProviderResult]] = []
        for query in queries[:reserve]:
            response = provider.search(query)
            cost += response.cost_cents
            for result in response.results:
                collected.append((query, result))
        with tenant_session(schema) as session:
            for query, result in collected:
                if svc.add_link_candidate(
                    session, subject_id=subject_id, run_id=run_id, provider=provider.name,
                    query=query, source_url=result.source_url, page_url=result.page_url,
                ) is not None:
                    candidates += 1
            final_run = session.get(DiscoveryRun, run_id)
            if final_run is not None:
                svc.finish_run(
                    session, workspace_id=workspace_id, actor_staff_id=None, run=final_run,
                    status=RunStatus.partial if capped else RunStatus.completed,
                    calls_made=reserve, cost_cents=cost, candidates_found=candidates,
                )
        return "completed"
    except Exception as exc:
        _finish(schema, workspace_id, run_id, status=RunStatus.failed,
                calls_made=reserve, cost_cents=cost, candidates_found=candidates,
                error=str(exc)[:1000])
        return "failed"


def _due(frequency: ScanFrequency, last_scan: datetime | None) -> bool:
    if frequency == ScanFrequency.off:
        return False
    if last_scan is None:
        return True
    window = timedelta(days=1) if frequency == ScanFrequency.daily else timedelta(days=7)
    return datetime.now(UTC) - last_scan >= window


@celery.task(name="worker.dispatch_scheduled_scans")
def dispatch_scheduled_scans() -> int:
    """Beat: enqueue due scans per workspace (enforceable subjects + their ready assets)."""
    with public_session() as session:
        workspace_ids = list(session.scalars(select(Workspace.id)).all())

    dispatched = 0
    for workspace_id in workspace_ids:
        schema = schema_for_workspace(workspace_id)
        with tenant_session(schema) as session:
            settings = svc.get_or_create_settings(session)
            # "Due" is judged from the last actual SCAN (not intake or blocked runs).
            last_scan = session.scalar(
                select(DiscoveryRun.started_at)
                .where(
                    DiscoveryRun.kind.in_([RunKind.reverse_image, RunKind.keyword]),
                    DiscoveryRun.status != RunStatus.blocked,
                )
                .order_by(DiscoveryRun.started_at.desc())
                .limit(1)
            )
            if not _due(settings.scan_frequency, last_scan):
                continue
            subjects = list(
                session.scalars(
                    select(Subject).where(Subject.status == SubjectStatus.active)
                ).all()
            )
            plan: list[tuple[str, int, int | None]] = []
            for subject in subjects:
                if not subject_enforcement(session, subject)["enforceable"]:
                    continue
                plan.append(("keyword", subject.id, None))
                for aid in session.scalars(
                    select(Asset.id).where(
                        Asset.subject_id == subject.id, Asset.status == AssetStatus.ready
                    )
                ).all():
                    plan.append(("reverse", subject.id, aid))
        for kind, subject_id, asset_id in plan:
            if kind == "keyword":
                keyword_scan.delay(workspace_id, subject_id)
            elif asset_id is not None:
                reverse_image_scan.delay(workspace_id, subject_id, asset_id)
            dispatched += 1
    return dispatched


@celery.task(name="worker.cleanup_expired_thumbnails")
def cleanup_expired_thumbnails() -> int:
    """Beat: delete candidate thumbnails + rows past the workspace retention window.

    Deletes the (sensitive) object bytes FIRST so a crash can't orphan them; a leftover row
    with a missing thumbnail self-heals on the next run.
    """
    with public_session() as session:
        workspace_ids = list(session.scalars(select(Workspace.id)).all())

    removed = 0
    storage = get_storage()
    for workspace_id in workspace_ids:
        schema = schema_for_workspace(workspace_id)
        with tenant_session(schema) as session:
            settings = svc.get_or_create_settings(session)
            cutoff = datetime.now(UTC) - timedelta(days=settings.thumbnail_retention_days)
            pairs = [
                (c.id, c.thumbnail_key)
                for c in session.scalars(
                    select(DiscoveryCandidate).where(
                        DiscoveryCandidate.thumbnail_key.is_not(None),
                        DiscoveryCandidate.discovered_at < cutoff,
                    )
                ).all()
                if c.thumbnail_key
            ]
        for _, key in pairs:
            storage.delete_object(key)
        with tenant_session(schema) as session:
            for candidate_id, _ in pairs:
                candidate = session.get(DiscoveryCandidate, candidate_id)
                if candidate is not None:
                    session.delete(candidate)
        removed += len(pairs)
    return removed
