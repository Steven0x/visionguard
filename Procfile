# honcho runs the three dev processes. `make dev` starts docker infra first.
api: uvicorn api.app.main:app --reload --port 8000
# Local dev runs on macOS, where Python 3.8+ (and billiard) default multiprocessing to the
# `spawn` start method. Celery's default prefork pool can't bootstrap under spawn — a spawned
# pool worker loses its task registry and crashes with "not enough values to unpack (expected
# 3, got 0)" in billiard's fast_trace_task, so NO task ever runs. We can't force `fork` on
# macOS either: fork-after-threads is unsafe for the native libs the worker loads (torch,
# Playwright), which crash or deadlock. So dev uses the thread pool (fork/spawn-agnostic, fine
# for our I/O-bound tasks). Production is Linux (docker/worker.Dockerfile), where the default
# start method is `fork` and the prefork pool works — it is intentionally left on prefork there.
worker: celery -A worker.celery_app.celery worker --loglevel=info --pool=threads --concurrency=4
beat: celery -A worker.celery_app.celery beat --loglevel=info
web: npm --prefix web run dev
