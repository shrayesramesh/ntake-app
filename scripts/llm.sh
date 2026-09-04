#!/usr/bin/env bash
#
# llm.sh — bring the local llamafile model server up/down for DEV (Mac/host).
#
# A convenience wrapper around the manual `llamafile --server ...` command
# (HOST_SETUP_GUIDE §7.2): starts it in the background with a PID file, waits
# until the OpenAI endpoint answers, and stops it cleanly. This is the *serving*
# side — deliberately separate from the app's config (which only knows the
# base_url URL, never the model file path).
#
#   scripts/llm.sh up       # start (idempotent; no-op if already serving)
#   scripts/llm.sh down     # stop the server this script started
#   scripts/llm.sh status   # is the endpoint answering?
#
# Paths default to the HOST_SETUP_GUIDE §7.1 location; override via env:
#   NTAKE_LLM_DIR    (default ~/.local/share/ntake/llm)
#   NTAKE_LLAMAFILE  (default $NTAKE_LLM_DIR/llamafile)
#   NTAKE_MODEL      (default $NTAKE_LLM_DIR/llama-3.1-8b-instruct.Q8_0.gguf;
#                     leave a self-contained model-llamafile's model empty)
#   NTAKE_LLM_HOST   (default 127.0.0.1)   NTAKE_LLM_PORT (default 8080)
#
# Note: does NOT pass --nobrowser (rejected by llamafile 0.10.5+; --server has
# no browser/TUI anyway).

set -euo pipefail

NTAKE_LLM_DIR="${NTAKE_LLM_DIR:-$HOME/.local/share/ntake/llm}"
NTAKE_LLAMAFILE="${NTAKE_LLAMAFILE:-$NTAKE_LLM_DIR/llamafile}"
NTAKE_MODEL="${NTAKE_MODEL:-$NTAKE_LLM_DIR/llama-3.1-8b-instruct.Q8_0.gguf}"
NTAKE_LLM_HOST="${NTAKE_LLM_HOST:-127.0.0.1}"
NTAKE_LLM_PORT="${NTAKE_LLM_PORT:-8080}"

PID_FILE="$NTAKE_LLM_DIR/server.pid"
LOG_FILE="$NTAKE_LLM_DIR/server.log"
BASE_URL="http://$NTAKE_LLM_HOST:$NTAKE_LLM_PORT"

_endpoint_up() {
  # 0 if /v1/models answers, else non-zero. Quiet, short timeout.
  curl -fsS --max-time 2 "$BASE_URL/v1/models" >/dev/null 2>&1
}

_running_pid() {
  # Echo the live PID from the PID file, or nothing.
  [ -f "$PID_FILE" ] || return 0
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "$pid"
  fi
}

cmd_up() {
  if _endpoint_up; then
    echo "llm: already serving at $BASE_URL (nothing to do)"
    return 0
  fi
  if [ ! -x "$NTAKE_LLAMAFILE" ]; then
    echo "llm: llamafile not found/executable at $NTAKE_LLAMAFILE" >&2
    echo "     acquire it per HOST_SETUP_GUIDE §7.1, or set NTAKE_LLAMAFILE." >&2
    return 1
  fi

  # Bare-binary shape needs -m <gguf>; a self-contained model-llamafile does not
  # (leave NTAKE_MODEL empty for that shape).
  local model_args=()
  if [ -n "$NTAKE_MODEL" ]; then
    if [ ! -f "$NTAKE_MODEL" ]; then
      echo "llm: model file not found at $NTAKE_MODEL" >&2
      echo "     acquire it per HOST_SETUP_GUIDE §7.1, or set NTAKE_MODEL (or" >&2
      echo "     empty it for a self-contained model-llamafile)." >&2
      return 1
    fi
    model_args=(-m "$NTAKE_MODEL")
  fi

  mkdir -p "$NTAKE_LLM_DIR"
  echo "llm: starting $NTAKE_LLAMAFILE on $BASE_URL (log: $LOG_FILE)"
  nohup "$NTAKE_LLAMAFILE" --server \
    --host "$NTAKE_LLM_HOST" --port "$NTAKE_LLM_PORT" \
    "${model_args[@]}" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"

  # Wait for readiness (model load can take tens of seconds).
  local deadline=$(( $(date +%s) + 120 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if _endpoint_up; then
      echo "llm: up (pid $(cat "$PID_FILE")) — $BASE_URL/v1/models is answering"
      return 0
    fi
    # If the process died during load, fail fast with a log pointer.
    if [ -z "$(_running_pid)" ]; then
      echo "llm: process exited during startup — see $LOG_FILE" >&2
      return 1
    fi
    sleep 1
  done
  echo "llm: timed out waiting for $BASE_URL to answer — see $LOG_FILE" >&2
  return 1
}

cmd_down() {
  local pid
  pid="$(_running_pid)"
  if [ -z "$pid" ]; then
    echo "llm: not running (no live PID in $PID_FILE)"
    rm -f "$PID_FILE"
    return 0
  fi
  echo "llm: stopping pid $pid"
  kill "$pid" 2>/dev/null || true
  # Give it a moment; escalate if it lingers.
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "llm: still alive, sending SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  echo "llm: stopped"
}

cmd_status() {
  if _endpoint_up; then
    local pid
    pid="$(_running_pid)"
    echo "llm: UP at $BASE_URL${pid:+ (pid $pid)}"
    return 0
  fi
  echo "llm: DOWN (no answer at $BASE_URL)"
  return 1
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  *)
    echo "usage: scripts/llm.sh {up|down|status}" >&2
    exit 2
    ;;
esac
