#!/usr/bin/env bash
#
# secrets-token.sh — set (or rotate) the HMAC device-token secret into the
# stage's Secrets Manager secret `ntake-<stage>/token-secret` (AWS_LLD §5.1).
# The [HUMAN] out-of-band step that fills the EMPTY secret CDK creates: CDK owns
# the secret's existence (name/ARN/removal-policy); this command owns its value,
# so the secret material never enters the repo, the synthesized template, or
# CloudFormation state.
#
# The secret is the per-install HMAC key device tokens are hashed under. Rotating
# it invalidates ALL existing device tokens (every token must be re-minted), so
# rotate deliberately. Setting it the first time is a prerequisite for the
# authorizer + the pair exchange to work.
#
# The value is generated locally (openssl) or taken from NTAKE_TOKEN_SECRET; it
# is handed to `put-secret-value` via a 0600 temp file (never argv, which is
# visible in `ps`/history), stored as JSON {"secret": "..."}. The temp file is
# shredded on exit. This is a [HUMAN]-run step — an agent must NOT run it.
#
# Usage:
#   ./secrets-token.sh [dev|prod]              # generate a fresh random secret
#   NTAKE_TOKEN_SECRET=... ./secrets-token.sh [dev|prod]   # use a provided value
#   ./secrets-token.sh --show [dev|prod]       # print current metadata only
#
# Stage defaults to 'dev'. Writing to 'prod' requires a typed confirmation.
#
set -euo pipefail

readonly EXPECTED_ACCOUNT="111037110464"
readonly EXPECTED_REGION="us-east-1"

die() { echo "secrets-token: $*" >&2; exit 1; }

SHOW_ONLY=0
STAGE=""
for arg in "$@"; do
  case "$arg" in
    --show) SHOW_ONLY=1 ;;
    dev|prod) STAGE="$arg" ;;
    *) die "unknown argument: $arg (usage: [--show] [dev|prod])" ;;
  esac
done
STAGE="${STAGE:-dev}"
readonly SECRET_ID="ntake-${STAGE}/token-secret"

command -v aws >/dev/null 2>&1 || die "aws CLI not found on PATH."

# --- account/region guard ---
CALLER_ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" \
  || die "no usable AWS credentials (aws sts get-caller-identity failed)."
[ "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT" ] \
  || die "wrong account: '$CALLER_ACCOUNT' (expected $EXPECTED_ACCOUNT)."
REGION="$(aws configure get region 2>/dev/null || echo "$EXPECTED_REGION")"

if [ "$SHOW_ONLY" = "1" ]; then
  aws secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$REGION" \
    --query '{Name:Name,LastChangedDate:LastChangedDate,Arn:ARN}' --output table
  exit 0
fi

if [ "$STAGE" = "prod" ]; then
  echo "About to set the PROD device-token secret ($SECRET_ID)."
  echo "This INVALIDATES every existing prod device token (all must be re-minted)."
  printf 'Type "set prod token" to continue: '
  read -r confirm
  [ "$confirm" = "set prod token" ] || die "aborted."
fi

# --- obtain the secret value (env or freshly generated) ---
VALUE="${NTAKE_TOKEN_SECRET:-}"
if [ -z "$VALUE" ]; then
  command -v openssl >/dev/null 2>&1 || die "openssl not found; set NTAKE_TOKEN_SECRET instead."
  VALUE="$(openssl rand -base64 48 | tr -d '\n')"
  echo "Generated a fresh 48-byte random token secret."
fi

TMP="$(mktemp)"; chmod 600 "$TMP"
cleanup() { command -v shred >/dev/null 2>&1 && shred -u "$TMP" 2>/dev/null || rm -f "$TMP"; }
trap cleanup EXIT
printf '{"secret":"%s"}' "$VALUE" > "$TMP"

aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ID" --region "$REGION" \
  --secret-string "file://$TMP" >/dev/null

echo "Set $SECRET_ID (stage=$STAGE, region=$REGION). Existing tokens under the"
echo "old secret are now invalid; mint new ones with scripts/mint.py."
