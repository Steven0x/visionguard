# VisionGuard Celery worker image. Heavy: real embedder (torch/open-clip), evidence capture
# (Playwright + Chromium) and timestamping. Own image so the lightweight api/beat don't carry it.
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
# ml + capture + obs extras. Real backends only run on the worker.
RUN pip install ".[ml,capture,obs]"

# ── Runtime ─────────────────────────────────────────────────────────────────────
FROM python:3.12.7-slim@sha256:c24c34b502635f1f7c4e99dc09a2cbd85d480b7dcfd077198c8b5a501bbff9d1 AS runtime

ENV PYTHONUNBUFFERED=1 PATH="/venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN useradd --create-home --uid 10001 vg
WORKDIR /app

COPY --from=build /venv /venv

# Install the Chromium build + its OS libraries, into a world-readable path the vg user can run.
RUN mkdir -p /ms-playwright && chown vg:vg /ms-playwright \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY --chown=vg:vg api ./api
COPY --chown=vg:vg worker ./worker
COPY --chown=vg:vg pyproject.toml ./

USER vg

# Concurrency stays modest — capture + embedding are memory-heavy. Tune per machine size.
CMD ["celery", "-A", "worker.celery_app.celery", "worker", "--loglevel=info", "--concurrency=2"]
