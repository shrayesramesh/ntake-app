#!/usr/bin/env bash
#
# live_llm_ui.sh — bring the app up against the LIVE local LLM for browser UI
# testing. Default mode is a persistent local sandbox; --demo is a fresh,
# resettable Alex/Sam scenario.
#
# HOW THIS DIFFERS FROM `make smoke`:
#   * `make smoke` (scripts/integration_smoke_on_host.py): an isolated TEMP DB, a
#     hardcoded "Smoke Household", the FAKE assistant, and 12 fake-shaped
#     assertions. Self-cleaning; proves the plumbing. Its assistant checks assume
#     deterministic fake proposals a real model won't reproduce.
#   * default `make ui-live`: persistent ./calendar.db + configured local sandbox
#     household, live local LLM, sample events, token, and debug panel.
#   * `make ui-demo`: fresh temporary DB/config, full Alex/Sam demo scenario,
#     live local LLM, token, and debug panel. The demo DB is removed on exit.
#
# PREREQUISITE: the llamafile model server must already be answering on the
# configured base URL. Bring it up with `make llm-up` first; this script does not
# start the model.
#
# Usage:
#   scripts/live_llm_ui.sh --demo     # resettable Alex/Sam demo DB + live LLM
#   scripts/live_llm_ui.sh --no-serve # do everything but block-serving (CI-ish)
#   HOST=0.0.0.0 scripts/live_llm_ui.sh   # bind LAN too (no TLS; trusted net only)
#
# ENV VARS THIS SCRIPT READS (all optional — sensible defaults):
#   NTAKE_CONFIG        household config path (default ~/.config/ntake/family.toml)
#   NTAKE_TOKEN_SECRET  device-token secret; if unset, a STABLE one is persisted
#                       to <config-dir>/token_secret (see below) so tokens survive
#                       re-runs. Set it yourself to control it.
#   NTAKE_LLM_BASE_URL  model server URL (default http://localhost:8080)
#   NTAKE_MEMBER        member to mint the token for (default: first adult in cfg)
#   HOST / PORT         app bind (default 127.0.0.1 / 8000)
#
# ENV VARS THIS SCRIPT SETS for the app process (the whole "flip" — no code edit;
# get_assistant_config() reads these, committed default stays fake so tests are
# unaffected). Documented in HOST_SETUP_GUIDE §7.4:
#   NTAKE_ASSISTANT_KIND=local   NTAKE_LLM_MODEL=<served id>   NTAKE_LLM_BASE_URL
#
# OUT-OF-REPO FILES THIS SCRIPT MAY CREATE (never in the repo):
#   live mode: <config-dir>/family.toml and <config-dir>/token_secret
#   demo mode: a temporary DB/config plus /tmp/ntake_ui_demo_token (chmod 600,
#              removed when the demo launcher exits)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PY=.venv/bin/python
UVICORN=.venv/bin/uvicorn
BASE_URL="${NTAKE_LLM_BASE_URL:-http://localhost:8080}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
SERVE=1
MODE="live"
for arg in "$@"; do
  case "$arg" in
    --demo) MODE="demo" ;;
    --no-serve) SERVE=0 ;;
    *) echo "usage: $0 [--demo] [--no-serve]" >&2; exit 2 ;;
  esac
done

test -x "$PY" || { echo "No venv — run 'make setup' first." >&2; exit 1; }

# --- 0. config + token secret ---------------------------------------------
DEMO_DIR=""
DEMO_TOKEN_FILE=""
if [ "$MODE" = "demo" ]; then
  DEMO_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ntake-ui-demo.XXXXXX")"
  DEMO_TOKEN_FILE="${TMPDIR:-/tmp}/ntake_ui_demo_token"
  rm -f "$DEMO_TOKEN_FILE"
  export NTAKE_CONFIG="$DEMO_DIR/family.toml"
  export CALENDAR_DB_URL="sqlite:///$DEMO_DIR/calendar.db"
  export NTAKE_TOKEN_SECRET="$($PY -c 'import secrets; print(secrets.token_urlsafe(32))')"
  "$PY" - "$NTAKE_CONFIG" <<'PYEOF'
from pathlib import Path
import sys
from app.demo.alex_sam_household import ALEX_SAM_TOML
Path(sys.argv[1]).write_text(ALEX_SAM_TOML)
PYEOF
  echo "Demo mode: fresh Alex/Sam DB at $DEMO_DIR"
else
  : "${NTAKE_CONFIG:=$HOME/.config/ntake/family.toml}"
  export NTAKE_CONFIG
  if [ ! -f "$NTAKE_CONFIG" ]; then
    echo "No config at $NTAKE_CONFIG — scaffolding from the example."
    mkdir -p "$(dirname "$NTAKE_CONFIG")"
    cp family.example.toml "$NTAKE_CONFIG"
    echo "  Edit it with your household, then re-run. Using the example for now."
  fi
  if [ -z "${NTAKE_TOKEN_SECRET:-}" ]; then
    # Persist a STABLE secret the script owns (out-of-repo, alongside the config),
    # so re-runs keep previously-minted device tokens valid instead of invalidating
    # them each time. Referenced only here + in this file's header (no ad-hoc env
    # file to source). Override by exporting NTAKE_TOKEN_SECRET yourself.
    SECRET_FILE="$(dirname "$NTAKE_CONFIG")/token_secret"
    if [ ! -f "$SECRET_FILE" ]; then
      umask 077
      $PY -c 'import secrets;print(secrets.token_urlsafe(32))' > "$SECRET_FILE"
      echo "Wrote a stable token secret to $SECRET_FILE (chmod 600, out-of-repo)."
    fi
    export NTAKE_TOKEN_SECRET="$(cat "$SECRET_FILE")"
  fi
fi

# --- 1. preflight: the live model must be up (other session's job) --------
echo "Preflight: checking the LLM server at $BASE_URL ..."
MODELS_JSON="$(curl -fsS --max-time 3 "$BASE_URL/v1/models" 2>/dev/null || true)"
if [ -z "$MODELS_JSON" ]; then
  echo "ERROR: no model server at $BASE_URL/v1/models." >&2
  echo "  The infra/host session must run 'make llm-up' first (HOST_SETUP §7)." >&2
  exit 1
fi
# The served model id — llamafile reports the full gguf path; check_health does
# an EXACT match, so the app's model MUST equal this for a green health probe.
SERVED_MODEL="$(printf '%s' "$MODELS_JSON" \
  | $PY -c 'import sys,json; d=json.load(sys.stdin); print((d.get("data") or [{}])[0].get("id",""))')"
[ -n "$SERVED_MODEL" ] && echo "  Served model id: $SERVED_MODEL"

# --- 2. flip the assistant to the live backend (env, test-safe) -----------
# get_assistant_config() reads these; the COMMITTED default stays fake, so the
# test suite is unaffected. This is the whole "flip" — one env var, no code edit.
export NTAKE_ASSISTANT_KIND=local
export NTAKE_LLM_BASE_URL="$BASE_URL"
[ -n "$SERVED_MODEL" ] && export NTAKE_LLM_MODEL="$SERVED_MODEL"

# --- 3. start the app (startup migrates DB to head + seeds from config) ---
LOG=/tmp/ntake_live_ui.log
[ "$MODE" = "demo" ] && LOG=/tmp/ntake_demo_ui.log
echo "Starting app on http://$HOST:$PORT (log: $LOG) ..."
"$UVICORN" app.main:app --host "$HOST" --port "$PORT" > "$LOG" 2>&1 &
APP_PID=$!
cleanup() {
  kill "$APP_PID" 2>/dev/null || true
  if [ -n "$DEMO_DIR" ]; then
    rm -rf "$DEMO_DIR"
  fi
  if [ -n "$DEMO_TOKEN_FILE" ]; then
    rm -f "$DEMO_TOKEN_FILE"
  fi
}
trap cleanup EXIT INT TERM

# wait for health
for _ in $(seq 1 30); do
  curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 \
  || { echo "App failed to start — see $LOG" >&2; tail -n 20 "$LOG" >&2; exit 1; }
echo "  App healthy."

# --- 4. seed demo scenario or regular sample events -----------------------
if [ "$MODE" = "demo" ]; then
  "$PY" - <<'PYEOF'
from app.demo.alex_sam_household import seed_alex_sam_household
from app.persistence.database import SessionLocal
session = SessionLocal()
try:
    seed_alex_sam_household(session)
finally:
    session.close()
PYEOF
else
  "$PY" -m app.manage seed-events >/dev/null 2>&1 || true
fi

# --- 5. mint a device token for a member ----------------------------------
# Default to the first adult in the config if NTAKE_MEMBER isn't set.
MEMBER="${NTAKE_MEMBER:-$($PY - <<'PYEOF'
import os, tomllib
cfg = os.environ["NTAKE_CONFIG"]
with open(cfg, "rb") as f:
    data = tomllib.load(f)
members = data.get("members", [])
adults = [m for m in members if m.get("role") == "adult"]
pick = (adults or members or [{}])[0]
print(pick.get("display_name", ""))
PYEOF
)}"
TOKEN=""
TOKEN_NOTE=""
if [ -n "$MEMBER" ]; then
  # With a PERSISTENT DB + stable secret, a previously-minted token stays valid,
  # so don't mint a fresh one every run (that just accumulates tokens and the
  # plaintext can't be re-shown). Mint only if this member has NO active token,
  # unless NTAKE_NEW_TOKEN=1 forces one.
  HAS_ACTIVE="$($PY - "$MEMBER" <<'PYEOF'
import sys
from app.persistence.database import SessionLocal
from app.persistence.models import DeviceToken, Member
name = sys.argv[1]
s = SessionLocal()
try:
    m = s.query(Member).filter_by(display_name=name).first()
    active = 0
    if m:
        active = (
            s.query(DeviceToken)
            .filter(DeviceToken.member_id == m.id, DeviceToken.revoked_at.is_(None))
            .count()
        )
    print(active)
finally:
    s.close()
PYEOF
)"
  if [ "${NTAKE_NEW_TOKEN:-0}" = "1" ] || [ "${HAS_ACTIVE:-0}" = "0" ]; then
    TOKEN="$($PY -m app.manage gen-token "$MEMBER" --label "live-ui $(date +%H%M%S)" \
              2>/dev/null | awk 'NF && $1 !~ /Device|Enrolled/ {print $1; exit}')"
  else
    TOKEN_NOTE="(reusing $MEMBER's existing active token — plaintext shown at first"
    TOKEN_NOTE="$TOKEN_NOTE mint. Set NTAKE_NEW_TOKEN=1 to mint another.)"
  fi
fi

if [ "$MODE" = "demo" ]; then
  [ -n "$TOKEN" ] || { echo "ERROR: demo token was not minted." >&2; exit 1; }
  umask 077
  printf '%s\n' "$TOKEN" > "$DEMO_TOKEN_FILE"
fi

# --- 6. serve + print how to use it ---------------------------------------
SHOWN_HOST="$HOST"; [ "$HOST" = "0.0.0.0" ] && SHOWN_HOST="<this-machine-LAN-IP>"
DEMO_TOKEN_NOTE=""
[ "$MODE" = "demo" ] && DEMO_TOKEN_NOTE="demo token: make ui-demo-token"
cat <<EOF

==================================================================
 Live-LLM UI session is UP.
   URL:    http://$SHOWN_HOST:$PORT/
   member: ${MEMBER:-<none minted>}
   token:  ${TOKEN:-<reuse your prior token — see note below>}
   ${TOKEN_NOTE}
   ${DEMO_TOKEN_NOTE}
   model:  ${SERVED_MODEL:-<default>}  (backend: local)
   mode:   $MODE
   DB:     ${CALENDAR_DB_URL:-./calendar.db}   log: $LOG

 In the browser: paste the token, then capture free text. Expand the
 "LLM debug trace" panel under a proposal to see both prompts + the raw
 model replies + resolved ids. Cards show full record detail.
==================================================================
EOF

if [ "$SERVE" -eq 1 ]; then
  echo "Ctrl-C to stop (the app is a child of this script)."
  wait "$APP_PID"
else
  echo "--no-serve: stopping the app now."
fi
