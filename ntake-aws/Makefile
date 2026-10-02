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

# Python sources under the gate. Parked modules (see pyproject header) are still
# linted by ruff (harmless) but excluded from mypy + coverage until Session 2.
SRC    := core handlers adapters tracer tests

# Coverage gate: the lifted live core is unit-tested (LLD §8); parked modules are
# omitted in pyproject so this measures only Session-1 live code.
COV_MIN := 95

.DEFAULT_GOAL := help

.PHONY: \
  help setup \
  test test-core test-data test-assistant test-api test-infra \
  lint format typecheck coverage check \
  ddb-up ddb-down synth deploy-dev deploy-prod bedrock-smoke \
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

test: ## Run the full local pytest suite (unit + integration tiers; no cloud)
	$(_require_pytest)
	$(PYTEST)

test-core: ## Focused: engine/schemas/temporal/tokens/boundary (Phase 1)
	$(_require_pytest)
	$(PYTEST) tests/core tests/test_boundary.py

test-data: ## Focused: repository + access patterns (Phase 2/3; Session 2+)
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

typecheck: ## Static type check (mypy; parked modules excluded in pyproject)
	@test -x $(MYPY) || { echo "No venv — run 'make setup' first."; exit 1; }
	$(MYPY) core handlers adapters tracer tests

coverage: ## Run tests with a coverage report (terminal, shows missing lines)
	$(_require_pytest)
	$(PYTEST) --cov=core --cov-report=term-missing

check: ## THE GATE: lint + typecheck + coverage-enforced tests
	@$(MAKE) lint
	@$(MAKE) typecheck
	$(_require_pytest)
	$(PYTEST) --cov=core --cov-report=term-missing --cov-fail-under=$(COV_MIN)
	@echo "check: all passed."

# --- DynamoDB Local (access-pattern tests; Session 3+) ---------------------

ddb-up: ## Start DynamoDB Local (container; skipped-if-absent)
	bash scripts/ddb_local.sh up

ddb-down: ## Stop DynamoDB Local
	bash scripts/ddb_local.sh down

# --- Infra (CDK; TypeScript) -----------------------------------------------

synth: ## cdk synth the empty stack (infra compiles; NO deploy)
	cd infra && npm run build && cdk synth

deploy-dev: ## [HUMAN] cdk deploy the dev tracer slice (needs AWS creds; Session 1.5)
	cd infra && npm run build && cdk deploy TracerStack-dev

deploy-prod: ## [HUMAN] cdk deploy the prod stage (needs AWS creds; not Session 1)
	cd infra && npm run build && cdk deploy NtakeStack-prod

bedrock-smoke: ## [HUMAN] dev-stage checks vs REAL Bedrock (Session 8; needs deploy)
	$(PY) scripts/bedrock_smoke.py

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
