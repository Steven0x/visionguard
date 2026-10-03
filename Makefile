.DEFAULT_GOAL := help
.PHONY: help install dev infra-up infra-down migrate test test-api test-web lint lint-api lint-web fmt seed-admin seed-demo check-venv lens-tunnel

# Load .env if present so local commands see DATABASE_URL / REDIS_URL etc.
ifneq (,$(wildcard .env))
include .env
export
endif

# Always run backend Python through the project venv, never whatever `python`/`pytest` happens to
# be on PATH (system/anaconda). Targets that need it depend on `check-venv`, which fails fast with
# a clear message if the venv is missing. (CI installs into its own interpreter and calls the tools
# directly, so it never touches these targets.)
PY := .venv/bin/python

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install backend (editable, with dev extras) and frontend deps
	pip install -e ".[dev]"
	npm --prefix web install

infra-up: ## Start local Postgres + Redis + MinIO (and create the bucket)
	docker compose up -d db redis minio minio-setup

infra-down: ## Stop local infra
	docker compose down

dev: infra-up ## Run api, worker and web locally
	honcho start

check-venv: ## Fail fast if the project venv is missing
	@test -x "$(PY)" || { \
		echo "ERROR: project venv not found at '$(PY)'."; \
		echo "Create it and install deps, e.g.:"; \
		echo "  python3.12 -m venv .venv && . .venv/bin/activate && make install"; \
		exit 1; \
	}

migrate: check-venv ## Apply migrations to public + every tenant schema
	$(PY) -m api.app.cli migrate

test: test-api test-web ## Run all tests

test-api: check-venv ## Backend tests (pytest, via the project venv)
	$(PY) -m pytest

test-web: ## Frontend tests (vitest)
	npm --prefix web run test -- --run

lint: lint-api lint-web ## Lint + typecheck everything

lint-api: check-venv ## ruff + mypy
	$(PY) -m ruff check api worker
	$(PY) -m mypy api worker

lint-web: ## eslint + tsc
	npm --prefix web run lint
	npm --prefix web run typecheck

fmt: check-venv ## Auto-format backend
	$(PY) -m ruff check --fix api worker
	$(PY) -m ruff format api worker

seed-admin: check-venv ## Create the first admin staff member (EMAIL=, CLERK_USER_ID=)
	$(PY) -m api.app.cli seed-first-admin --email "$(EMAIL)" --clerk-user-id "$(CLERK_USER_ID)"

seed-demo: check-venv ## Seed a clickable demo workspace + subject + images + review-inbox candidates
	$(PY) -m api.app.cli seed-demo

lens-tunnel: check-venv ## DEV ONLY: expose local MinIO assets to Lens via a GUARDED cloudflared tunnel
	@# Runs a dev-only allowlist proxy (presigned GETs of the assets bucket only — no other bucket,
	@# listings, console, writes, or unsigned requests) behind the tunnel. Refuses default MinIO
	@# creds and APP_ENV != dev. Auto-stops after 15 min. See api/app/dev/lens_proxy.py.
	$(PY) -m api.app.dev.lens_proxy
