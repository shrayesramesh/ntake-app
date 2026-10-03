# Makefile — thin task launcher for the ntake-aws (AWS-native) build.
#
# Mirrors the old app's thin-launcher pattern: this Makefile delegates real work
# to scripts/ and the venv binaries (each recipe line runs in its own subshell,
# so calling .venv/bin/* directly is more reliable than activating the venv).
# Run every target from the ntake-aws/ package root.
#
# Common usage:
#   make setup     # one-time (or after dep changes): venv + install + verify
#   make check     # the gate: lint + typecheck + coverage-enforced tests
#   make synth     # cdk synth (infra compiles; no deploy)

VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff
MYPY   := $(VENV)/bin/mypy

# Python sources under the gate (lint scope). All six formerly-parked action
# modules are live as of Session 3 — no exclusions remain.
SRC    := core handlers adapters tracer tests

# Coverage gate: the lifted + ported core is unit/flow-tested (LLD §8).
COV_MIN := 95

.DEFAULT_GOAL := help

.PHONY: \
  help setup \
  test test-core test-data test-assistant test-api test-infra \
  lint format typecheck coverage check \
  synth integration deploy-dev deploy-prod dev-reset bedrock-preflight \
  setup-aws clean

help: ## Show available targets
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | sed -E 's/^([a-zA-Z_-]+):.*## (.*)/  \1|\2/' \
	  | awk -F'|' '{ printf "  %-16s %s\n", $$1, $$2 }'

# --- Setup -----------------------------------------------------------------

setup: ## Create venv, install pinned deps, verify (delegates to scripts/setup.sh)
	bash scripts/setup.sh

# --- Tests (full + focused per Part-I phase) -------------------------------

_require_pytest = @test -x $(PYTEST) || { echo "No venv — run 'make setup' first."; exit 1; }

# Tier 1 never collects the Tier-2 integration suite (it needs real AWS); that
# runs only via `make integration`.
TIER1_IGNORE := --ignore=tests/integration

test: ## Run the full local Tier-1 pytest suite (in-memory; no cloud)
	$(_require_pytest)
	$(PYTEST) $(TIER1_IGNORE)

test-core: ## Focused: engine/schemas/temporal/tokens/boundary (Phase 1)
	$(_require_pytest)
	$(PYTEST) tests/core tests/test_boundary.py

test-data: ## Focused: repository + action handlers (Tier 1, in-memory)
	$(_require_pytest)
	$(PYTEST) tests/data

test-assistant: ## Focused: LINK + PROPOSE Bedrock seams (Phase 3; Session 4+)
	$(_require_pytest)
	$(PYTEST) tests/assistant

test-api: ## Focused: thin handlers + authorizer + publish boundary (Phase 4; Session 6+)
	$(_require_pytest)
	$(PYTEST) tests/api

test-infra: ## Focused: cdk synth + template assertions (Phase 5; Session 7+)
	$(_require_pytest)
	$(PYTEST) tests/infra

# --- Quality checks --------------------------------------------------------

lint: ## Check lint + format (ruff, no changes)
	@test -x $(RUFF) || { echo "No venv — run 'make setup' first."; exit 1; }
	$(RUFF) check $(SRC)
	$(RUFF) format --check $(SRC)

format: ## Auto-fix lint + format (ruff)
	@test -x $(RUFF) || { echo "No venv — run 'make setup' first."; exit 1; }
	$(RUFF) check --fix $(SRC)
	$(RUFF) format $(SRC)

typecheck: ## Static type check (mypy)
	@test -x $(MYPY) || { echo "No venv — run 'make setup' first."; exit 1; }
	$(MYPY) core handlers adapters tracer tests

coverage: ## Run tests with a coverage report (terminal, shows missing lines)
	$(_require_pytest)
	$(PYTEST) $(TIER1_IGNORE) --cov=core --cov-report=term-missing

check: ## THE GATE (Tier 1): lint + typecheck + coverage-enforced in-memory tests
	@$(MAKE) lint
	@$(MAKE) typecheck
	$(_require_pytest)
	$(PYTEST) $(TIER1_IGNORE) --cov=core --cov-report=term-missing --cov-fail-under=$(COV_MIN)
	@echo "check: all passed."

# --- Infra (CDK; TypeScript) -----------------------------------------------

synth: ## cdk synth the stacks (infra compiles; NO deploy)
	cd infra && npm run build && cdk synth

# --- Tier 2: integration against the REAL dev stage ([HUMAN]-invoked) -------

integration: ## [HUMAN] Tier 2: run the integration suite vs the real ntake-dev table (sts self-check; DEPLOY=1 deploys NtakeStack-dev first)
	bash scripts/integration.sh

bedrock-preflight: ## [HUMAN] diagnose Bedrock model-access prerequisites (FTU form, marketplace perms, Nova-vs-Claude probe)
	$(PY) scripts/bedrock_preflight.py

deploy-dev: ## [HUMAN] cdk deploy the dev tracer slice (needs AWS creds; Session 1.5)
	cd infra && npm run build && cdk deploy TracerStack-dev

deploy-prod: ## [HUMAN] cdk deploy the prod stage (needs AWS creds)
	cd infra && npm run build && cdk deploy NtakeStack-prod

dev-reset: ## [HUMAN] destroy NtakeStack-dev (DROPS the dev table + ALL its data) for a clean slate; recreate with 'make integration DEPLOY=1'
	@echo "This DESTROYS NtakeStack-dev and all data in the ntake-dev table (dev only, removalPolicy=DESTROY)."
	@echo "Prod is never touched. Recreate the empty table with: make integration DEPLOY=1"
	cd infra && npm run build && cdk destroy NtakeStack-dev

# --- Account preflight (one-shot; [HUMAN]-run) -----------------------------

setup-aws: ## [HUMAN] assert non-root admin on 111037110464 + cdk bootstrap
	bash scripts/setup-aws.sh

# --- Maintenance -----------------------------------------------------------

clean: ## Remove venv, Python caches, and infra build artifacts
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf infra/cdk.out infra/node_modules
	find infra/bin infra/lib -name '*.js' -o -name '*.d.ts' 2>/dev/null | xargs rm -f 2>/dev/null || true
	@echo "cleaned."
