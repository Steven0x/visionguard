"""Celery application. Broker/result backend come from REDIS_URL.

Slice 0 ships one trivial task so the worker boots and CI can exercise it. Real discovery,
fingerprinting and evidence tasks arrive in later slices.
"""

from __future__ import annotations

from api.app.config import get_settings
from celery import Celery

settings = get_settings()

celery = Celery(
    "visionguard",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["worker.tasks", "worker.discovery"],
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
}
