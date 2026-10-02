#!/usr/bin/env bash
#
# ddb_local.sh — start/stop DynamoDB Local for access-pattern tests (Session 3+).
#
# `make ddb-up` / `make ddb-down` delegate here. DynamoDB Local runs as a
# container on localhost:8000. This is intentionally SKIPPED-IF-ABSENT: if no
# container runtime (docker) is on PATH, we print a clear notice and exit 0 so
# the gate never fails on a machine without docker — the Dynamo access-pattern
# tests are themselves skipped-if-absent (Session 3 wires that marker).
#
# Session 1 ships this as the agreed thin tooling; the first real consumer is
# Session 3 (DynamoRepository against DynamoDB Local).
#
set -euo pipefail

readonly CONTAINER="ntake-ddb-local"
readonly IMAGE="amazon/dynamodb-local:latest"
readonly PORT="8000"

action="${1:-}"

runtime=""
if command -v docker >/dev/null 2>&1; then
  runtime="docker"
fi

if [[ -z "$runtime" ]]; then
  echo "ddb-local: no container runtime (docker) on PATH." >&2
  echo "ddb-local: DynamoDB Local is optional — access-pattern tests skip when it is absent." >&2
  exit 0
fi

case "$action" in
  up)
    if "$runtime" ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
      echo "ddb-local: already running (${CONTAINER} on :${PORT})."
      exit 0
    fi
    echo "ddb-local: starting ${CONTAINER} (${IMAGE}) on :${PORT}..."
    "$runtime" run -d --rm --name "$CONTAINER" -p "${PORT}:8000" "$IMAGE" >/dev/null
    echo "ddb-local: up on http://localhost:${PORT}."
    ;;
  down)
    if "$runtime" ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
      echo "ddb-local: stopping ${CONTAINER}..."
      "$runtime" stop "$CONTAINER" >/dev/null
      echo "ddb-local: down."
    else
      echo "ddb-local: not running — nothing to stop."
    fi
    ;;
  *)
    echo "usage: ddb_local.sh {up|down}" >&2
    exit 2
    ;;
esac
