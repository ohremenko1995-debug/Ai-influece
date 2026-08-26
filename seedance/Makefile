# ---------------------------------------------------------------------------
# seedance-gateway
# ---------------------------------------------------------------------------
SHELL := /bin/bash
.DEFAULT_GOAL := help
.ONESHELL:
.SHELLFLAGS := -e -o pipefail -c

UV     ?= uv
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	 | sort \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Create the venv and install the package with dev extras
	$(UV) venv $(VENV) --python 3.11
	$(UV) pip install --python $(BIN)/python -e '.[dev]'

.PHONY: lint
lint: ## ruff check + format check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

.PHONY: format
format: ## Apply ruff formatting
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

.PHONY: typecheck
typecheck: ## mypy --strict
	$(BIN)/mypy

.PHONY: test
test: ## Run the test suite (fully offline)
	$(BIN)/pytest

.PHONY: check
check: lint typecheck test ## Every gate

.PHONY: rates
rates: ## Print the current price comparison
	$(BIN)/seedance rates
