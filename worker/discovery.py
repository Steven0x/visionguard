"""Discovery Celery jobs: reverse-image + keyword scans, scheduling, thumbnail cleanup.

Scan tasks NEVER raise (eager-safe): failures are recorded on the run. The run row is created
and committed first, so a later failure can still be marked `failed`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api.app.db.base import schema_for_workspace
from api.app.db.session import public_session, tenant_session
from api.app.models.assets import Asset, AssetStatus
from api.app.models.discovery import (
    DiscoveryCandidate,
    DiscoveryRun,
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
    # 1) Create the run + make the gate/budget decision in a committed transaction.
    with tenant_session(schema) as session:
        subject = session.get(Subject, subject_id)
        asset = session.get(Asset, asset_id)
        if subject is None or asset is None or asset.status != AssetStatus.ready:
            return "skipped"
        settings = svc.get_or_create_settings(session)
        tineye_enabled = settings.tineye_enabled
        budget = settings.monthly_call_budget
        run = svc.start_run(
            session,
            kind=RunKind.reverse_image,
            subject_id=subject_id,
            asset_id=asset_id,
        )
        run_id = run.id
        enforceable = subject_enforcement(session, subject)["enforceable"]
        mtd = svc.month_to_date_calls(session)
        image_url = get_storage().generate_download_url(
            asset.file_key, filename=asset.file_name, expires_in=_SIGNED_TTL
        )
        if not enforceable:
            svc.finish_run(
                session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                status=RunStatus.blocked,
            )
            return "blocked"
        if mtd >= budget:
            svc.finish_run(
                session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                status=RunStatus.blocked,
            )
            return "blocked"

    calls = cost = candidates = 0
    try:
        providers = get_reverse_image_providers(tineye_enabled=tineye_enabled)
        allowed = max(0, budget - mtd)
        to_call = providers[:allowed]
        capped = len(to_call) < len(providers)
        collected: list[tuple[str, ProviderResult]] = []
        for provider in to_call:
            response = provider.search(image_url)
            calls += response.calls_made
            cost += response.cost_cents
            for result in response.results:
                collected.append((provider.name, result))
        with tenant_session(schema) as session:
            for provider_name, result in collected:
                candidate = svc.add_image_candidate(
                    session,
                    schema=schema,
                    subject_id=subject_id,
                    run_id=run_id,
                    provider=provider_name,
                    query=None,
                    source_url=result.source_url,
                    page_url=result.page_url,
                )
                if candidate is not None:
                    candidates += 1
            final_run = session.get(DiscoveryRun, run_id)
            if final_run is not None:
                svc.finish_run(
                    session, workspace_id=workspace_id, actor_staff_id=None, run=final_run,
                    status=RunStatus.partial if capped else RunStatus.completed,
                    calls_made=calls, cost_cents=cost, candidates_found=candidates,
                )
        return "completed"
    except Exception as exc:  # never raises — eager-safe
        _finish(
            schema, workspace_id, run_id, status=RunStatus.failed,
            calls_made=calls, cost_cents=cost, candidates_found=candidates,
            error=str(exc)[:1000],
        )
        return "failed"


@celery.task(name="worker.keyword_scan")
def keyword_scan(workspace_id: int, subject_id: int) -> str:
    schema = schema_for_workspace(workspace_id)
    with tenant_session(schema) as session:
        subject = session.get(Subject, subject_id)
        if subject is None:
            return "skipped"
        settings = svc.get_or_create_settings(session)
        budget = settings.monthly_call_budget
        run = svc.start_run(
            session, kind=RunKind.keyword, subject_id=subject_id, provider="keyword"
        )
        run_id = run.id
        enforceable = subject_enforcement(session, subject)["enforceable"]
        mtd = svc.month_to_date_calls(session)
        from api.app.services.keywords import identifiers as get_identifiers

        queries = get_identifiers(session, subject)
        if not enforceable:
            svc.finish_run(
                session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                status=RunStatus.blocked,
            )
            return "blocked"
        if mtd >= budget:
            svc.finish_run(
                session, workspace_id=workspace_id, actor_staff_id=None, run=run,
                status=RunStatus.blocked,
            )
            return "blocked"

    calls = cost = candidates = 0
    try:
        provider = get_keyword_provider()
        allowed = max(0, budget - mtd)
        to_run = queries[:allowed]
        capped = len(to_run) < len(queries)
        collected_links: list[tuple[str, ProviderResult]] = []
        for query in to_run:
            response = provider.search(query)
            calls += response.calls_made
            cost += response.cost_cents
            for result in response.results:
                collected_links.append((query, result))
        with tenant_session(schema) as session:
            for query, result in collected_links:
                candidate = svc.add_link_candidate(
                    session,
                    subject_id=subject_id,
                    run_id=run_id,
                    provider=provider.name,
                    query=query,
                    source_url=result.source_url,
                    page_url=result.page_url,
                )
                if candidate is not None:
                    candidates += 1
            final_run = session.get(DiscoveryRun, run_id)
            if final_run is not None:
                svc.finish_run(
                    session, workspace_id=workspace_id, actor_staff_id=None, run=final_run,
                    status=RunStatus.partial if capped else RunStatus.completed,
                    calls_made=calls, cost_cents=cost, candidates_found=candidates,
                )
        return "completed"
    except Exception as exc:
        _finish(
            schema, workspace_id, run_id, status=RunStatus.failed,
            calls_made=calls, cost_cents=cost, candidates_found=candidates,
            error=str(exc)[:1000],
        )
        return "failed"


def _due(frequency: ScanFrequency, last_started: datetime | None) -> bool:
    if frequency == ScanFrequency.off:
        return False
    if last_started is None:
        return True
    window = timedelta(days=1) if frequency == ScanFrequency.daily else timedelta(days=7)
    return datetime.now(UTC) - last_started >= window


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
            last = session.scalar(
                select(DiscoveryRun.started_at)
                .order_by(DiscoveryRun.started_at.desc())
                .limit(1)
            )
            if not _due(settings.scan_frequency, last):
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
                asset_ids = list(
                    session.scalars(
                        select(Asset.id).where(
                            Asset.subject_id == subject.id, Asset.status == AssetStatus.ready
                        )
                    ).all()
                )
                for aid in asset_ids:
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
    """Beat: delete candidate thumbnails + rows past the workspace retention window."""
    with public_session() as session:
        workspace_ids = list(session.scalars(select(Workspace.id)).all())

    removed = 0
    storage = get_storage()
    for workspace_id in workspace_ids:
        schema = schema_for_workspace(workspace_id)
        with tenant_session(schema) as session:
            settings = svc.get_or_create_settings(session)
            cutoff = datetime.now(UTC) - timedelta(days=settings.thumbnail_retention_days)
            expired = list(
                session.scalars(
                    select(DiscoveryCandidate).where(
                        DiscoveryCandidate.thumbnail_key.is_not(None),
                        DiscoveryCandidate.discovered_at < cutoff,
                    )
                ).all()
            )
            keys = [c.thumbnail_key for c in expired if c.thumbnail_key]
            for candidate in expired:
                session.delete(candidate)
            session.flush()
            session.commit()
        for key in keys:
            storage.delete_object(key)
            removed += 1
    return removed
