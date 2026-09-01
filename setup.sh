#!/usr/bin/env bash
#
# setup.sh — one-shot environment setup + verification for Pop!_OS (Ubuntu-based).
#
# Gets you from a fresh checkout to "tests passing" so you KNOW the environment
# is correct before coding (or before handing off to the local agent).
#
# What it does (idempotent — safe to re-run):
#   1. Checks Python 3.12+ and that the venv module is available.
#   2. Creates/uses a .venv virtualenv.
#   3. Installs pinned deps from requirements.txt.
#   4. Runs the test suite and reports pass/fail clearly.
#
# It does NOT touch Tailscale, the browser, or any device — those are separate,
# human-only steps (see shovel-ready/tasks_tailscale_*.md).
#
# Usage:   bash setup.sh
#
set -euo pipefail

# ---- pretty output ---------------------------------------------------------
GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YEL=$'\033[0;33m'; NC=$'\033[0m'
ok()   { echo "${GREEN}✓${NC} $*"; }
warn() { echo "${YEL}!${NC} $*"; }
err()  { echo "${RED}✗${NC} $*" >&2; }
step() { echo; echo "==> $*"; }

# Always run from the script's own directory (project root).
cd "$(dirname "$0")"

# ---- 1. Python check -------------------------------------------------------
step "Checking Python"
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not found. On Pop!_OS: sudo apt update && sudo apt install python3 python3-venv"
  exit 1
fi
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
ok "python3 found: $(python3 --version 2>&1) (need >= 3.12)"
# Fail if < 3.12 (sort -V trick).
if [ "$(printf '%s\n3.12\n' "$PYVER" | sort -V | head -1)" != "3.12" ]; then
  err "Python $PYVER is too old; need 3.12+. Install a newer Python."
  exit 1
fi

# ---- 2. venv module check --------------------------------------------------
step "Checking venv support"
if ! python3 -c 'import venv' >/dev/null 2>&1; then
  err "The 'venv' module is missing. On Pop!_OS run: sudo apt install python3-venv"
  exit 1
fi
ok "venv module available"

# ---- 3. Create venv --------------------------------------------------------
step "Setting up virtualenv (.venv)"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ok "created .venv"
else
  ok ".venv already exists (reusing)"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
ok "pip upgraded"

# ---- 4. Install deps -------------------------------------------------------
step "Installing dependencies (requirements.txt)"
if [ ! -f requirements.txt ]; then
  err "requirements.txt not found in $(pwd)."
  exit 1
fi
pip install --quiet -r requirements.txt
ok "dependencies installed"

# ---- 5. Run tests ----------------------------------------------------------
step "Running tests (pytest)"
# One cosmetic StarletteDeprecationWarning about httpx/httpx2 is EXPECTED and
# harmless — do not install httpx2 to 'fix' it.
if python -m pytest -q; then
  echo
  ok "ALL TESTS PASSED — environment is set up correctly."
  echo
  echo "Next:"
  echo "  • Run the app:   source .venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
  echo "  • Health check:  curl -s http://127.0.0.1:8000/health"
  echo "  • Agent tasks:   see AGENT_START_HERE.md (checkpoints 1d, 1e next)"
  echo "  • Tailscale (human-only): shovel-ready/tasks_tailscale_host_serve.md"
else
  echo
  err "Tests failed. The environment or code is not correct yet — see output above."
  exit 1
fi
