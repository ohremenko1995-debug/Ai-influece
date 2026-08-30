# Identity Lock — everything a contributor runs.
#
# `make check` is the gate: it is exactly what CI runs, so a green local run
# means a green pipeline.

PY      ?= python3
VENV    ?= .venv
BIN     := $(VENV)/bin
SUITE   ?= suites/demo.yaml
OUT     ?= var
PORT    ?= 8420

.DEFAULT_GOAL := help
.PHONY: help install web demo bootstrap calibrate run compare serve test cov lint format typecheck check clean distclean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --upgrade pip

install: $(BIN)/python ## Create the virtualenv and install the project with dev extras
	$(BIN)/python -m pip install --quiet -e '.[dev]'
	@echo "installed — try: make demo"

web: ## Build the dashboard bundle into the Python package
	cd web && pnpm install --frozen-lockfile && pnpm build

demo: install ## Render references, run every recipe, compare, write reports
	$(BIN)/identitylock demo --suite $(SUITE) --out $(OUT)

bootstrap: ## Render the reference sets for the suite
	$(BIN)/identitylock bootstrap --suite $(SUITE) --out $(OUT)

calibrate: ## Re-derive thresholds from a validation set and write them into the suite
	$(BIN)/identitylock calibrate --suite $(SUITE) --out $(OUT) --write

run: ## Run one recipe: make run RECIPE=locked
	$(BIN)/identitylock run --suite $(SUITE) --out $(OUT) --recipe $(RECIPE) --gate

serve: ## Open the dashboard over the stored results
	$(BIN)/identitylock serve --out $(OUT) --port $(PORT)

test: ## Run the test suite
	$(BIN)/python -m pytest

cov: ## Run the test suite with a coverage report
	$(BIN)/python -m pytest --cov=identitylock --cov-report=term-missing

lint: ## Lint
	$(BIN)/ruff check .

format: ## Format in place
	$(BIN)/ruff format .

typecheck: ## Type-check under mypy --strict
	$(BIN)/mypy

check: lint typecheck test ## Everything CI runs
	$(BIN)/ruff format --check .
	@echo "all gates green"

clean: ## Remove run artefacts and rendered references
	rm -rf $(OUT) suites/references

distclean: clean ## Also remove the virtualenv and node modules
	rm -rf $(VENV) web/node_modules .mypy_cache .ruff_cache .pytest_cache .coverage
