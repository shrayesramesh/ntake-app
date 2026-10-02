#!/usr/bin/env bash
#
# setup.sh — create the venv, install pinned deps, and verify (ntake-aws).
#
# Single-purpose: `make setup` delegates here. Idempotent — safe to re-run after
# a requirements change. Operates from the ntake-aws package root (its parent).
#
set -euo pipefail

cd "$(dirname "$0")/.."   # ntake-aws/

VENV=".venv"
PY="${VENV}/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "setup: creating virtualenv at ${VENV}..."
  python3 -m venv "$VENV"
fi

echo "setup: upgrading pip..."
"$PY" -m pip install --quiet --upgrade pip

echo "setup: installing pinned Python deps (requirements.txt)..."
"$PY" -m pip install --quiet -r requirements.txt

# Infra (CDK/TS) deps: install only if npm is present (synth needs them). The
# Python gate does not depend on this, so a missing npm is a warning, not a fail.
if command -v npm >/dev/null 2>&1; then
  echo "setup: installing infra (CDK) node deps..."
  ( cd infra && npm install --silent --no-fund --no-audit )
else
  echo "setup: npm not found — skipping infra deps (needed only for 'make synth')." >&2
fi

echo "setup: verifying tool imports..."
"$PY" - <<'PY'
import importlib

for mod in ("pydantic", "pytest", "ruff", "mypy", "boto3"):
    importlib.import_module(mod)
import core.engine.engine  # noqa: F401 — the lifted core imports cleanly
print("setup: OK — venv ready, core imports clean.")
PY

echo "setup: done. Next: 'make check'."
