# VisionGuard Celery beat (scheduler) image. Light — beat only enqueues scheduled jobs, so it
# needs neither ml nor capture. Beat MUST run as exactly one machine (see deploy/fly/beat.toml);
# a per-job Redis lock (worker/locks.py) makes a stray second beat a no-op regardless.
FROM python:3.12.7-slim@sha256:c24c34b502635f1f7c4e99dc09a2cbd85d480b7dcfd077198c8b5a501bbff9d1 AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml ./
COPY api ./api
COPY worker ./worker
RUN pip install ".[obs]"

# ── Runtime ─────────────────────────────────────────────────────────────────────
FROM python:3.12.7-slim@sha256:c24c34b502635f1f7c4e99dc09a2cbd85d480b7dcfd077198c8b5a501bbff9d1 AS runtime

ENV PYTHONUNBUFFERED=1 PATH="/venv/bin:$PATH"
RUN useradd --create-home --uid 10001 vg
WORKDIR /app

COPY --from=build /venv /venv
COPY --chown=vg:vg api ./api
COPY --chown=vg:vg worker ./worker
COPY --chown=vg:vg pyproject.toml ./

USER vg

# Store the beat schedule under the writable home dir.
CMD ["celery", "-A", "worker.celery_app.celery", "beat", "--loglevel=info", \
     "--schedule", "/home/vg/celerybeat-schedule"]
