#!/usr/bin/env bash
#
# secrets-anthropic.sh — put (or rotate) the Anthropic API key into the
# stage's Secrets Manager secret. The [HUMAN] out-of-band step that fills the
# EMPTY secret CDK creates (AWS_LLD §7.1 / AWS_HLD decision §10).
#
# Why a script and not inline CDK: the key VALUE must never enter the repo, the
# synthesized template, or CloudFormation state. CDK owns the secret's existence;
# this command owns its value. Same command rotates the key later — no redeploy,
# the capture Lambda re-reads on its next cold start.
#
# The key is NEVER passed as a command argument (argv is visible in `ps` and
# shell history). It is read from the ANTHROPIC_API_KEY env var, or prompted for
# silently (no echo). It is handed to `put-secret-value` via a temp file with
# 0600 perms (not `--secret-string <value>`, which would also hit argv), and the
# temp file is shredded on exit.
#
# This is a [HUMAN]-run step: it writes to the account. An agent must NOT run it.
#
# Usage:
#   ANTHROPIC_API_KEY=sk-ant-... ./secrets-anthropic.sh [dev|prod]   # from env
#   ./secrets-anthropic.sh [dev|prod]                                # prompt (no echo)
#   ./secrets-anthropic.sh --show [dev|prod]                         # print current metadata only
#
# Stage defaults to 'dev'. Writing to 'prod' requires an explicit typed
# confirmation (it is a production secret).
#
set -euo pipefail

# --- Pinned targets (AWS_HLD §11, AWS_LLD header) ---
readonly EXPECTED_ACCOUNT="111037110464"
readonly EXPECTED_REGION="us-east-1"
# Workspace id stored alongside the key in the secret; override with
# ANTHROPIC_WORKSPACE_ID if it changes.
readonly WORKSPACE_ID="${ANTHROPIC_WORKSPACE_ID:-wrkspc_01V3XNZDmGXtsHeX2KVayeNY}"

die() { echo "secrets-anthropic: $*" >&2; exit 1; }

# --- Parse args: optional --show flag + optional stage ---
SHOW_ONLY=0
STAGE=""
for arg in "$@"; do
  case "$arg" in
    --show) SHOW_ONLY=1 ;;
    dev|prod) STAGE="$arg" ;;
    *) die "unknown argument '${arg}' (usage: ./secrets-anthropic.sh [--show] [dev|prod])" ;;
  esac
done
STAGE="${STAGE:-dev}"
readonly SECRET_ID="ntake-${STAGE}/anthropic-api-key"

# --- 0. Tooling + identity preflight (match setup-aws.sh posture) ---
command -v aws >/dev/null 2>&1 || die "AWS CLI ('aws') not found on PATH."

CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text 2>/dev/null)" \
  || die "not authenticated. Configure credentials for ${EXPECTED_ACCOUNT} first."
ACTUAL_ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)"
[[ "$ACTUAL_ACCOUNT" == "$EXPECTED_ACCOUNT" ]] \
  || die "wrong account: authenticated as ${ACTUAL_ACCOUNT}, expected ${EXPECTED_ACCOUNT} (${CALLER_ARN})."

echo "secrets-anthropic: account ${ACTUAL_ACCOUNT}, region ${EXPECTED_REGION}, secret ${SECRET_ID}"

# --- --show: print metadata only, never the value ---
if [[ "$SHOW_ONLY" == 1 ]]; then
  aws secretsmanager describe-secret \
    --secret-id "$SECRET_ID" --region "$EXPECTED_REGION" \
    --query '{Name:Name,LastChanged:LastChangedDate,VersionStages:VersionIdsToStages}' \
    --output table \
    || die "secret '${SECRET_ID}' not found. Deploy NtakeStack-${STAGE} first (it creates the empty secret)."
  exit 0
fi

# --- Confirm the secret exists (CDK must have created it) ---
aws secretsmanager describe-secret \
  --secret-id "$SECRET_ID" --region "$EXPECTED_REGION" >/dev/null 2>&1 \
  || die "secret '${SECRET_ID}' not found. Deploy NtakeStack-${STAGE} first — CDK creates it empty, this script fills it."

# --- prod guard ---
if [[ "$STAGE" == "prod" ]]; then
  read -r -p "Writing the PRODUCTION Anthropic key (${SECRET_ID}). Type 'prod' to confirm: " confirm
  [[ "$confirm" == "prod" ]] || die "aborted (prod not confirmed)."
fi

# --- Obtain the key: env var, else silent prompt. Never from argv. ---
KEY="${ANTHROPIC_API_KEY:-}"
if [[ -z "$KEY" ]]; then
  read -r -s -p "Paste the Anthropic API key (input hidden): " KEY
  echo
fi
[[ -n "$KEY" ]] || die "no key provided (set ANTHROPIC_API_KEY or paste at the prompt)."
case "$KEY" in
  sk-ant-*) : ;;
  *) echo "secrets-anthropic: warning — key does not start with 'sk-ant-'; continuing anyway." >&2 ;;
esac

# --- Write {api_key, workspace_id} JSON via a 0600 temp file (value out of argv) ---
TMP="$(mktemp)"
chmod 600 "$TMP"
cleanup() {
  command -v shred >/dev/null 2>&1 && shred -u "$TMP" 2>/dev/null || rm -f "$TMP"
  unset KEY
}
trap cleanup EXIT
# Build JSON with python3 so the key is escaped correctly (never hand-built).
KEY="$KEY" WS="$WORKSPACE_ID" OUT="$TMP" python3 -c '
import json, os
with open(os.environ["OUT"], "w") as f:
    json.dump({"api_key": os.environ["KEY"], "workspace_id": os.environ["WS"]}, f)
' || die "failed to assemble the secret JSON."

aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ID" \
  --region "$EXPECTED_REGION" \
  --secret-string "file://${TMP}" >/dev/null \
  || die "put-secret-value failed for '${SECRET_ID}'."

echo "secrets-anthropic: ✅ wrote ${SECRET_ID} as {api_key, workspace_id} JSON."
echo "secrets-anthropic: (rotate anytime by re-running this script; no redeploy needed.)"
