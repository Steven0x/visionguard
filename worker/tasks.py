"""Celery tasks. Slice 0: a health-check task only."""

from __future__ import annotations

from worker.celery_app import celery


@celery.task(name="worker.ping")
def ping() -> str:
    return "pong"
