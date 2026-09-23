.DEFAULT_GOAL := help
.PHONY: help install dev infra-up infra-down migrate test test-api test-web lint lint-api lint-web fmt seed-admin

# Load .env if present so local commands see DATABASE_URL / REDIS_URL etc.
ifneq (,$(wildcard .env))
include .env
export
endif

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install backend (editable, with dev extras) and frontend deps
	pip install -e ".[dev]"
	npm --prefix web install

infra-up: ## Start local Postgres + Redis
	docker compose up -d db redis

infra-down: ## Stop local infra
	docker compose down

dev: infra-up ## Run api, worker and web locally
	honcho start

migrate: ## Apply migrations to public + every tenant schema
	python -m api.app.cli migrate

test: test-api test-web ## Run all tests

test-api: ## Backend tests (pytest)
	pytest

test-web: ## Frontend tests (vitest)
	npm --prefix web run test -- --run

lint: lint-api lint-web ## Lint + typecheck everything

lint-api: ## ruff + mypy
	ruff check api worker
	mypy api worker

lint-web: ## eslint + tsc
	npm --prefix web run lint
	npm --prefix web run typecheck

fmt: ## Auto-format backend
	ruff check --fix api worker
	ruff format api worker

seed-admin: ## Create the first admin staff member (EMAIL=, CLERK_USER_ID=)
	python -m api.app.cli seed-first-admin --email "$(EMAIL)" --clerk-user-id "$(CLERK_USER_ID)"
