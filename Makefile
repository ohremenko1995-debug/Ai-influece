# ---------------------------------------------------------------------------
# InfluencerOS task runner
#
# Two ways to work:
#   * Containers  — `make up` runs the whole stack via compose (recommended).
#   * Native      — `make install` builds a local venv + node_modules so the
#                   quality gates (lint/typecheck/test) run without Docker.
#
# `make help` lists every target.
# ---------------------------------------------------------------------------
SHELL := /bin/bash
.DEFAULT_GOAL := help
.ONESHELL:

COMPOSE      ?= docker compose
PYTHON       ?= python3.12
UV           ?= uv
PNPM         ?= pnpm

API_DIR      := apps/api
WEB_DIR      := apps/web
WORKER_DIR   := apps/worker
VENV         := $(API_DIR)/.venv
VENV_BIN     := $(VENV)/bin
OPENAPI_JSON := docs/api/openapi.json

# Native runs talk to services on localhost; compose runs use the network aliases.
NATIVE_ENV := POSTGRES_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 \
              S3_ENDPOINT_URL=http://127.0.0.1:9000 \
              S3_PUBLIC_ENDPOINT_URL=http://127.0.0.1:9000

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	 | sort \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Environment ------------------------------------------------------------

.PHONY: env
env: ## Create .env from .env.example if missing
	@if [ -f .env ]; then
		echo ".env already exists — leaving it untouched"
	else
		cp .env.example .env
		echo "Created .env from .env.example. Review it before running anything real."
	fi

.PHONY: install
install: install-api install-web ## Install backend venv and frontend node_modules

.PHONY: install-api
install-api: ## Create apps/api/.venv and install API + dev dependencies
	$(UV) venv --python $(PYTHON) $(VENV)
	$(UV) pip install --python $(VENV_BIN)/python -r $(API_DIR)/pyproject.toml --extra dev
	$(UV) pip install --python $(VENV_BIN)/python --no-deps -e $(API_DIR)

.PHONY: install-web
install-web: ## Install the pnpm workspace
	$(PNPM) install

# --- Container stack --------------------------------------------------------

.PHONY: up
up: env ## Start the full stack in the background
	$(COMPOSE) up -d --build
	@echo "API  -> http://localhost:8000/docs"
	@echo "Web  -> http://localhost:3000"
	@echo "MinIO-> http://localhost:9001"

.PHONY: down
down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

.PHONY: down-hard
down-hard: ## Stop the stack and DELETE all local data volumes
	$(COMPOSE) down --volumes --remove-orphans

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: logs
logs: ## Tail logs for all services (SERVICE=api to narrow)
	$(COMPOSE) logs -f --tail=200 $(SERVICE)

.PHONY: build
build: ## Rebuild all images
	$(COMPOSE) build

.PHONY: api-shell
api-shell: ## Open a shell in the running api container
	$(COMPOSE) exec api bash

.PHONY: db-shell
db-shell: ## Open psql against the dev database
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-influenceros} -d $${POSTGRES_DB:-influenceros}

# --- Database ---------------------------------------------------------------

.PHONY: migrate
migrate: ## Apply all migrations to the dev database
	cd $(API_DIR) && $(NATIVE_ENV) ../../$(VENV_BIN)/alembic upgrade head

.PHONY: migrate-docker
migrate-docker: ## Apply all migrations inside the api container
	$(COMPOSE) exec api alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration: make migration M="add assets"
	@if [ -z "$(M)" ]; then echo 'Usage: make migration M="short description"'; exit 1; fi
	cd $(API_DIR) && $(NATIVE_ENV) ../../$(VENV_BIN)/alembic revision --autogenerate -m "$(M)"

.PHONY: downgrade
downgrade: ## Roll back one migration
	cd $(API_DIR) && $(NATIVE_ENV) ../../$(VENV_BIN)/alembic downgrade -1

.PHONY: seed
seed: ## Seed the dev organization, roles and demo users
	cd $(API_DIR) && $(NATIVE_ENV) ../../$(VENV_BIN)/python -m app.cli seed

# --- Quality gates ----------------------------------------------------------

.PHONY: check
check: lint typecheck test ## Run every quality gate

.PHONY: lint
lint: lint-api lint-web ## Lint backend and frontend

.PHONY: lint-api
lint-api: ## Ruff lint + format check
	$(VENV_BIN)/ruff check $(API_DIR) $(WORKER_DIR)
	$(VENV_BIN)/ruff format --check $(API_DIR) $(WORKER_DIR)

.PHONY: lint-web
lint-web: ## ESLint + Prettier check
	$(PNPM) run lint
	$(PNPM) run format:check

.PHONY: format
format: format-api format-web ## Autoformat everything

.PHONY: format-api
format-api: ## Ruff format + import fixes
	$(VENV_BIN)/ruff check --fix $(API_DIR) $(WORKER_DIR)
	$(VENV_BIN)/ruff format $(API_DIR) $(WORKER_DIR)

.PHONY: format-web
format-web: ## Prettier write
	$(PNPM) run format

.PHONY: typecheck
typecheck: typecheck-api typecheck-web ## Type-check backend and frontend

.PHONY: typecheck-api
typecheck-api: ## MyPy strict
	cd $(API_DIR) && ../../$(VENV_BIN)/mypy .

.PHONY: typecheck-web
typecheck-web: ## tsc --noEmit across the workspace
	$(PNPM) run typecheck

.PHONY: test
test: test-api test-web ## Run backend and frontend unit tests

.PHONY: test-api
test-api: ## Pytest against the test database
	cd $(API_DIR) && $(NATIVE_ENV) ../../$(VENV_BIN)/pytest

.PHONY: test-api-docker
test-api-docker: ## Pytest inside the api container
	$(COMPOSE) exec api pytest

.PHONY: test-web
test-web: ## Vitest
	$(PNPM) run test

.PHONY: e2e
e2e: ## Playwright end-to-end suite (needs the stack running)
	$(PNPM) --filter @influenceros/web run e2e

# --- API contract -----------------------------------------------------------

.PHONY: openapi
openapi: ## Export docs/api/openapi.json and regenerate packages/types
	mkdir -p $(dir $(OPENAPI_JSON))
	cd $(API_DIR) && ../../$(VENV_BIN)/python -m app.cli export-openapi --output ../../$(OPENAPI_JSON)
	$(PNPM) --filter @influenceros/types run generate

.PHONY: clean
clean: ## Remove caches and build output
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \
	  -o -name .mypy_cache -o -name .next -o -name .turbo \) -prune -exec rm -rf {} +
	rm -f $(OPENAPI_JSON)
