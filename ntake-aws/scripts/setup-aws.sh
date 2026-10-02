#!/usr/bin/env bash
#
# setup-aws.sh — one-shot AWS account preflight for the AWS-native rebuild.
#
# What it does (and nothing more — single-purpose, idempotent, safe to re-run):
#   1. Assert the CLI is authenticated as the NON-ROOT admin on the target
#      account (111037110464) in the target region (us-east-1).
#   2. Run `cdk bootstrap aws://111037110464/us-east-1` (idempotent by design —
#      re-running against an already-bootstrapped env is a no-op/update).
#
# This is a [HUMAN]-run step (AWS_PLAN Phase 0c / Session 0.2): the operator runs
# it with their own credentials AFTER the two console actions (0a: non-root admin
# + CLI creds; 0b: Bedrock model access). An agent must NOT run this — it touches
# the account. The script itself creates no IAM, no secrets, no stack resources;
# bootstrap provisions only the standard CDK toolkit stack (CDKToolkit).
#
# Prereqs the operator must have in place first:
#   - AWS CLI v2 and the AWS CDK CLI (`cdk`) installed and on PATH.
#   - CLI credentials configured for the non-root admin (0a) — e.g. an IAM
#     Identity Center / SSO session or an IAM user's access keys. MFA either way.
#   - Bedrock model access enabled in us-east-1 (0b) — not checked here (it is a
#     console-only, account-level opt-in; its absence surfaces at first Converse).
#
# Usage:
#   ./setup-aws.sh                 # assert identity, then bootstrap
#   ./setup-aws.sh --check-only    # assert identity only; skip bootstrap
#
set -euo pipefail

# --- Pinned targets (AWS_HLD §11, AWS_LLD header, AWS_PLAN Phase 0/1d) ---
readonly EXPECTED_ACCOUNT="111037110464"
readonly EXPECTED_REGION="us-east-1"

CHECK_ONLY=0
if [[ "${1:-}" == "--check-only" ]]; then
  CHECK_ONLY=1
elif [[ -n "${1:-}" ]]; then
  echo "error: unknown argument '${1}' (usage: ./setup-aws.sh [--check-only])" >&2
  exit 2
fi

die() { echo "setup-aws: $*" >&2; exit 1; }

# --- 0. Tooling presence (clear failure beats a cryptic one downstream) ---
command -v aws >/dev/null 2>&1 || die "AWS CLI ('aws') not found on PATH. Install AWS CLI v2 first."
if [[ "$CHECK_ONLY" -eq 0 ]]; then
  command -v cdk >/dev/null 2>&1 || die "AWS CDK CLI ('cdk') not found on PATH. Install it (e.g. 'npm i -g aws-cdk') before bootstrapping."
fi

# --- 1. Assert NON-ROOT admin on the expected account ---
# One STS call; parse without jq so there are no extra deps. --output text gives
# us "<Account>\t<Arn>" in field order Account, Arn (UserId omitted by --query).
echo "setup-aws: verifying caller identity (expect non-root on ${EXPECTED_ACCOUNT}, region ${EXPECTED_REGION})..."
IDENTITY="$(aws sts get-caller-identity \
  --query '[Account,Arn]' --output text 2>/dev/null)" \
  || die "'aws sts get-caller-identity' failed — are CLI credentials configured for the 0a non-root admin? (run 'aws configure' / start an SSO session)."

CALLER_ACCOUNT="$(printf '%s' "$IDENTITY" | cut -f1)"
CALLER_ARN="$(printf '%s' "$IDENTITY" | cut -f2)"

[[ "$CALLER_ACCOUNT" == "$EXPECTED_ACCOUNT" ]] \
  || die "wrong account: authenticated as ${CALLER_ACCOUNT}, expected ${EXPECTED_ACCOUNT}. Switch profiles/credentials."

# Root's ARN is exactly arn:aws:iam::<acct>:root. Reject it — 0a exists precisely
# so we never operate as root after bootstrap.
if [[ "$CALLER_ARN" == *":root" ]]; then
  die "authenticated as the ROOT user (${CALLER_ARN}). Do NOT use root — authenticate as the 0a non-root admin (IAM Identity Center user or IAM user)."
fi

echo "setup-aws: OK — non-root admin on ${EXPECTED_ACCOUNT}."
echo "           ARN: ${CALLER_ARN}"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "setup-aws: --check-only set; skipping bootstrap. Done."
  exit 0
fi

# --- 2. Bootstrap the CDK toolkit (idempotent) ---
# `cdk bootstrap` is safe to re-run: it creates the CDKToolkit stack if absent or
# updates it in place otherwise. Scope it explicitly to the pinned env so it can
# never bootstrap somewhere unintended regardless of ambient config.
echo "setup-aws: bootstrapping CDK toolkit at aws://${EXPECTED_ACCOUNT}/${EXPECTED_REGION} (idempotent)..."
cdk bootstrap "aws://${EXPECTED_ACCOUNT}/${EXPECTED_REGION}"

echo "setup-aws: done. Account preflight complete — future work is 'cdk deploy', no console."
