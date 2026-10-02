"""Worker smoke test: a REAL Celery worker process must run a task end to end.

This guards the macOS `spawn` breakage (a prefork pool worker under the spawn start method
crashes in billiard before running anything, so the inbox silently stops fingerprinting). Unlike
the eager ping test, this starts an actual worker subprocess over the Redis broker. It skips when
Redis is unreachable so a laptop without infra up still passes; CI always has Redis.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from api.app.config import get_settings

from worker.celery_app import celery
from worker.tasks import ping

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SMOKE_QUEUE = "worker_smoke"  # dedicated queue so a running dev worker can't steal the task


def _redis_reachable(url: str) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 6379), 1.0):
            return True
    except OSError:
        return False


def test_dev_procfile_uses_a_macos_safe_pool() -> None:
    """The dev worker must not use the default prefork pool: it is broken under macOS spawn.
    This pins the fix so a future edit can't silently regress local development."""
    worker_line = next(
        line for line in (_REPO_ROOT / "Procfile").read_text().splitlines()
        if line.startswith("worker:")
    )
    assert "--pool=threads" in worker_line or "--pool=solo" in worker_line, worker_line


def test_real_worker_runs_a_task_end_to_end() -> None:
    settings = get_settings()
    if not _redis_reachable(settings.redis_url):
        pytest.skip("Redis not reachable; start infra (make infra-up) to run the worker smoke test")

    # This process normally runs tasks eagerly (APP_ENV=test); turn that off so the task is
    # actually enqueued to Redis and consumed by the subprocess worker. Restore it afterwards.
    was_eager = celery.conf.task_always_eager
    celery.conf.task_always_eager = False
    # The subprocess is a genuine worker (APP_ENV=dev → not eager). --pool=threads matches the
    # dev Procfile and is spawn-safe on macOS; the extra flags cut single-worker boot time.
    proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable, "-m", "celery", "-A", "worker.celery_app.celery", "worker",
            "--pool=threads", "--concurrency=1", "--loglevel=warning",
            "-Q", _SMOKE_QUEUE, "--without-gossip", "--without-mingle", "--without-heartbeat",
        ],
        cwd=str(_REPO_ROOT),
        env={**os.environ, "APP_ENV": "dev"},
    )
    try:
        result = ping.apply_async(queue=_SMOKE_QUEUE)
        assert result.get(timeout=60) == "pong"
    finally:
        celery.conf.task_always_eager = was_eager
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
