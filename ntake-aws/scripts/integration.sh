#!/usr/bin/env bash
# integration.sh — the Tier-2 harness (AWS_PLAN "make integration", AWS_LLD §8).
#
# Runs the integration suite against the REAL dev-stage DynamoDB table
# (ntake-dev). This is a [HUMAN]-invoked step: it needs AWS credentials and (with
# DEPLOY=1) deploys. It NEVER silently skips — if creds are missing or point at
# the wrong account, it stops with configure instructions.
#
# Usage (from the ntake-aws/ package root):
#   make integration            # test whatever is already deployed on dev
#   make integration DEPLOY=1    # cdk deploy NtakeStack-dev first, then test
#
# Env knobs (sensible defaults):
#   NTAKE_ACCOUNT     expected account id      (default 111037110464)
#   NTAKE_REGION      region                   (default us-east-1)
#   NTAKE_TABLE_NAME  table under test         (default ntake-dev)
#   DEPLOY            "1" to deploy first       (default unset)
set -euo pipefail

ACCOUNT="${NTAKE_ACCOUNT:-111037110464}"
REGION="${NTAKE_REGION:-us-east-1}"
TABLE="${NTAKE_TABLE_NAME:-ntake-dev}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # ntake-aws/ root
VENV_PY="$HERE/.venv/bin/python"
PYTEST="$HERE/.venv/bin/pytest"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- 0. tooling present ----------------------------------------------------
command -v aws >/dev/null 2>&1 || die "aws CLI not found on PATH."
[ -x "$PYTEST" ] || die "No venv — run 'make setup' first."

# --- 1. credential + account self-check (NEVER silently skip) --------------
say "==> Checking AWS credentials (aws sts get-caller-identity)…"
if ! IDENTITY_JSON="$(aws sts get-caller-identity --output json 2>/dev/null)"; then
  cat >&2 <<EOF

ERROR: no usable AWS credentials.

  'make integration' runs against the REAL dev-stage table and requires AWS
  credentials for account ${ACCOUNT} in ${REGION}. Configure them, e.g.:

      aws configure            # set the non-root admin's access key + ${REGION}
      aws sts get-caller-identity   # confirm it returns the ${ACCOUNT} admin

  Then re-run 'make integration'. (This step is [HUMAN]-invoked by design —
  it is the only path that reads/writes the AWS account.)
EOF
  exit 1
fi

CALLER_ACCOUNT="$(printf '%s' "$IDENTITY_JSON" | sed -n 's/.*"Account"[: ]*"\([0-9]*\)".*/\1/p')"
CALLER_ARN="$(printf '%s' "$IDENTITY_JSON" | sed -n 's/.*"Arn"[: ]*"\([^"]*\)".*/\1/p')"
say "    authenticated as: ${CALLER_ARN:-<unknown>}"

if [ "$CALLER_ACCOUNT" != "$ACCOUNT" ]; then
  die "wrong account: credentials are for '${CALLER_ACCOUNT:-<none>}', expected '${ACCOUNT}'.
     Reconfigure the CLI for the dev account before running integration."
fi

# --- 2. optional deploy ----------------------------------------------------
if [ "${DEPLOY:-}" = "1" ]; then
  say "==> DEPLOY=1 — deploying NtakeStack-dev (cdk deploy)…"
  ( cd "$HERE/infra" && npm run build && cdk deploy NtakeStack-dev --require-approval never )
else
  say "==> DEPLOY not set — testing whatever is already deployed (pass DEPLOY=1 to deploy first)."
fi

# --- 3. confirm the table exists before running the suite ------------------
say "==> Confirming table '${TABLE}' exists in ${REGION}…"
if ! aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  die "table '${TABLE}' not found in ${REGION}.
     Deploy it first:  make integration DEPLOY=1   (or  make deploy-dev)."
fi

# --- 4. run the Tier-2 suite against the real table ------------------------
say "==> Running the Tier-2 integration suite against ${TABLE} (${REGION})…"
cd "$HERE"
# `-rA` surfaces recorded properties + the short test summary. Pass extra pytest
# args via PYTEST_ARGS, e.g.  make integration PYTEST_ARGS='-s'  to see the live
# LLM request/response prints from the observing client in the pipeline tests.
NTAKE_TABLE_NAME="$TABLE" NTAKE_REGION="$REGION" \
  "$PYTEST" tests/integration -v -rA ${PYTEST_ARGS:-}
say "integration: all passed against ${TABLE}."
