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

.PHONY: \
  help setup test \
  test-assistant test-identity test-persistence test-api test-web test-operations \
  update-expectations \
  run smoke ui-live ui-demo ui-demo-token llm-up llm-down llm-status \
  lint format typecheck coverage check \
  freeze clean

help: ## Show available targets
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | sed -E 's/^([a-zA-Z_-]+):.*## (.*)/  \1|\2/' \
	  | awk -F'|' '{ printf "  %-22s %s\n", $$1, $$2 }'

# --- Setup and focused tests -----------------------------------------

setup: ## Create venv, install deps, and run tests (delegates to setup.sh)
	bash setup.sh

test: ## Run the test suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore

test-assistant: ## Run the focused assistant/pipeline suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore tests/assistant

test-identity: ## Run the focused identity/device-token suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore tests/identity

test-persistence: ## Run the focused database/model/migration suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore tests/persistence

test-api: ## Run the focused JSON API and live-sync suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore tests/api

test-web: ## Run the focused PWA and server-rendered UI suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore tests/web

test-operations: ## Run the focused lifecycle, config, backup, and CLI suite
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -v -W ignore tests/operations

# --- Prompt snapshots ------------------------------------------------

update-expectations: ## Regenerate golden-file prompt/LLM expectations (review the diff!)
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	NTAKE_UPDATE_EXPECTATIONS=1 $(PYTEST) -q -W ignore tests/assistant/test_prompts.py
	@echo "Expectations regenerated — review 'git diff tests/expectations/'."

# --- Runtime and integration -----------------------------------------

run: ## Run the dev server (127.0.0.1:8000)
	@test -x $(UVICORN) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(UVICORN) app.main:app --reload --host 127.0.0.1 --port 8000

# --- Local quality checks --------------------------------------------

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

coverage: ## Run tests with coverage report (terminal, shows missing lines)
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -W ignore --cov=app --cov-report=term-missing

smoke: ## Host integration smoke (real server, temp DB, self-cleaning). --serve via script
	@test -x $(PY) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PY) scripts/integration_smoke_on_host.py

ui-live: ## Live-LLM UI session: persistent local sandbox + live model (needs 'make llm-up' first)
	bash scripts/live_llm_ui.sh

ui-demo: ## Live-LLM UI session: fresh Alex/Sam demo DB + live model (needs 'make llm-up' first)
	bash scripts/live_llm_ui.sh --demo

ui-demo-token: ## Print the active demo UI token (demo must be running)
	@token_file="$${TMPDIR:-/tmp}/ntake_ui_demo_token"; \
	  test -r "$$token_file" || { echo "No active demo token — run 'make ui-demo' first." >&2; exit 1; }; \
	  cat "$$token_file"

llm-up: ## Start the local llamafile model server (dev; PID-tracked, waits ready)
	bash scripts/llm.sh up

llm-down: ## Stop the local llamafile model server started by llm-up
	bash scripts/llm.sh down

llm-status: ## Is the local model server answering?
	bash scripts/llm.sh status

# --- Full quality gate ------------------------------------------------

check: ## Everything gate: lint + typecheck + coverage-enforced tests
	@$(MAKE) lint
	@$(MAKE) typecheck
	@test -x $(PYTEST) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PYTEST) -W ignore --cov=app --cov-report=term-missing --cov-fail-under=95
	@echo "check: all passed."

# --- Maintenance ------------------------------------------------------

freeze: ## Print exact installed versions (for updating requirements.txt)
	@test -x $(PIP) || { echo "No venv found — run 'make setup' first."; exit 1; }
	$(PIP) freeze

clean: ## Remove venv, caches, and the runtime SQLite DB
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f calendar.db
	@echo "cleaned."
