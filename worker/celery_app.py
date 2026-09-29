"""Celery application. Broker/result backend come from REDIS_URL.

Slice 0 ships one trivial task so the worker boots and CI can exercise it. Real discovery,
fingerprinting and evidence tasks arrive in later slices.
"""

from __future__ import annotations

from api.app.config import get_settings
from celery import Celery
from celery.signals import setup_logging

settings = get_settings()


@setup_logging.connect
def _configure_worker_logging(**_kwargs: object) -> None:
    """Own logging setup on the worker/beat (fires at process start, not import) so records go
    through the scrubber and Sentry is initialised if a DSN is set. Connecting to this signal
    also stops Celery from installing its own unscrubbed handlers."""
    from api.app.obs.logging import configure_logging
    from api.app.obs.sentry import init_sentry

    configure_logging(settings)
    init_sentry(settings)

celery = Celery(
    "visionguard",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["worker.tasks", "worker.discovery", "worker.evidence", "worker.rechecks"],
)

# In tests we run tasks inline (no broker needed).
celery.conf.task_always_eager = settings.app_env == "test"
celery.conf.task_eager_propagates = True

# Beat: dispatch due per-workspace scans hourly; purge expired candidate thumbnails daily.
celery.conf.beat_schedule = {
    "discovery-dispatch": {
        "task": "worker.dispatch_scheduled_scans",
        "schedule": 3600.0,
    },
    "discovery-cleanup": {
        "task": "worker.cleanup_expired_thumbnails",
        "schedule": 86400.0,
    },
    "evidence-retry-timestamps": {
        "task": "worker.retry_untimestamped_captures",
        "schedule": 86400.0,
    },
    # Slice 9: re-check open URLs and run the removed→monitoring→closed tail daily.
    "recheck-open-urls": {
        "task": "worker.recheck_open_urls",
        "schedule": 86400.0,
    },
    "monitoring-lifecycle": {
        "task": "worker.run_monitoring_lifecycle",
        "schedule": 86400.0,
    },
}
