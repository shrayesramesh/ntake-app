# Makefile — thin task launcher for the family calendar app.
#
# Delegates real environment setup (with checks) to setup.sh, and calls the
# venv's binaries directly (each recipe line runs in its own subshell, so
# activating the venv wouldn't persist — calling .venv/bin/* is more reliable).
#
# Common usage:
#   make setup     # one-time (or after dependency changes): venv + install + verify
#   make test      # run the test suite
#   make run       # run the dev server on 127.0.0.1:8000
#   make clean     # remove venv + caches + runtime DB

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
SRC  := app tests

.DEFAULT_GOAL := help

.PHONY: help setup test run lint format typecheck check freeze clean

help: ## Show available targets
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | sed -E 's/^([a-zA-Z_-]+):.*## (.*)/  \1|\2/' \
	  | awk -F'|' '{ printf "  %-10s %s\n", $$1, $$2 }'

setup: ## Create venv, install deps, and run tests (delegates to setup.sh)
	bash setup.sh

test: ## Run the test suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore

run: ## Run the dev server (127.0.0.1:8000)
	@test -x $(UVICORN) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(UVICORN) app.main:app --reload --host 127.0.0.1 --port 8000

lint: ## Check lint rules (ruff, no changes)
	@test -x $(RUFF) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(RUFF) check $(SRC)
	$(RUFF) format --check $(SRC)

format: ## Auto-fix lint + format the code (ruff)
	@test -x $(RUFF) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(RUFF) check --fix $(SRC)
	$(RUFF) format $(SRC)

typecheck: ## Static type check (mypy)
	@test -x $(MYPY) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(MYPY) app

check: ## Everything gate: lint + typecheck + tests (run before finishing a task)
	@$(MAKE) lint
	@$(MAKE) typecheck
	@$(MAKE) test
	@echo "check: all passed."

freeze: ## Print exact installed versions (for updating requirements.txt)
	@test -x $(PIP) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PIP) freeze

clean: ## Remove venv, caches, and the runtime SQLite DB
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f calendar.db
	@echo "cleaned."
