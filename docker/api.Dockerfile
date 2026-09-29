# VisionGuard API image. Multi-stage: build deps into a venv, then a slim non-root runtime.
# Pinned by digest so a rebuild is reproducible (update deliberately, not implicitly).
FROM python:3.12.7-slim@sha256:c24c34b502635f1f7c4e99dc09a2cbd85d480b7dcfd077198c8b5a501bbff9d1 AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Build tools for any wheels that need compiling; not carried into the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# The api image needs the error-tracking extra but NOT ml/capture (those live on the worker image).
COPY pyproject.toml ./
COPY api ./api
COPY worker ./worker
RUN pip install ".[obs]"

# ── Runtime ─────────────────────────────────────────────────────────────────────
FROM python:3.12.7-slim@sha256:c24c34b502635f1f7c4e99dc09a2cbd85d480b7dcfd077198c8b5a501bbff9d1 AS runtime

ENV PYTHONUNBUFFERED=1 PATH="/venv/bin:$PATH"
# Non-root user — the app never needs root at runtime.
RUN useradd --create-home --uid 10001 vg
WORKDIR /app

COPY --from=build /venv /venv
COPY --chown=vg:vg api ./api
COPY --chown=vg:vg worker ./worker
COPY --chown=vg:vg pyproject.toml ./

USER vg
EXPOSE 8000

# uvicorn (installed via the uvicorn[standard] dependency) with a couple of workers. Migrations
# are a SEPARATE release step (see deploy/fly), never run here. Liveness /healthz, readiness /readyz.
CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
