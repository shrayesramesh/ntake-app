#!/usr/bin/env python3
"""⚠️ THROWAWAY Session-1.5 validation driver (deleted with the tracer slice). ⚠️

Run by the [HUMAN] with their AWS creds (the agent has none). It seeds one device
token so the authorizer will admit it, then prints the token + the exact curl /
websocket commands for the three cloud-seam checks (IAM, Bedrock, WebSocket).

It reuses the REAL ``core.tokens.hash_token`` so the seeded hash matches what the
deployed authorizer computes from the same Secrets Manager secret — i.e. it mints
a token exactly the way the real minting path (Session 4c/6) eventually will.

Usage (from ntake-aws/, with the venv + AWS creds):

    .venv/bin/python scripts/tracer_validate.py

Reads the stack outputs below (edit if you redeploy with new values).
"""
# ruff: noqa: E501 — this file's body is printed shell-command text; wrapping the
# emitted curl/websocat lines would break copy-paste. Line length is not meaningful here.

from __future__ import annotations

import sys
from pathlib import Path

# The script lives in ntake-aws/scripts/; its parent is the package root where the
# `core` package lives. Put that on sys.path so `import core...` resolves no matter
# the cwd (running a file puts the file's own dir on sys.path, not the root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3

from core.tokens import generate_token, hash_token

# --- Deployed TracerStack-dev outputs (from `make deploy-dev`) ---------------
TABLE_NAME = "TracerStack-dev-TracerTable7D05654E-1GZ1MTSLFON8W"
TOKEN_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:111037110464:secret:"
    "TokenSecret75569B26-padc6vdm2uHx-joTaJ8"
)
HTTP_API_URL = "https://yrjwhuqqwe.execute-api.us-east-1.amazonaws.com"
WS_URL = "wss://4n0hoilz7i.execute-api.us-east-1.amazonaws.com/dev"
REGION = "us-east-1"


def main() -> None:
    sm = boto3.client("secretsmanager", region_name=REGION)
    secret = sm.get_secret_value(SecretId=TOKEN_SECRET_ARN)["SecretString"]

    token = generate_token()
    token_hash = hash_token(token, secret=secret)

    ddb = boto3.client("dynamodb", region_name=REGION)
    ddb.put_item(
        TableName=TABLE_NAME,
        Item={
            "pk": {"S": f"TOK#{token_hash}"},
            "sk": {"S": "#META"},
            "member_id": {"S": "MEM#alex"},
            "family_id": {"S": "FAM#tracer"},
        },
    )
    print(f"Seeded token for MEM#alex / FAM#tracer (hash {token_hash[:12]}...).\n")
    print(f"TOKEN={token}\n")

    print("=" * 72)
    print("STEP A — IAM seam (authorizer allow + scoped DynamoDB round trip):")
    print("=" * 72)
    print(f"""curl -s -H "Authorization: Bearer {token}" {HTTP_API_URL}/tracer-iam | python3 -m json.tool
# Expect 200 JSON: iam "ok ...", round_tripped_item present, authorizer_context
# {{member_id: MEM#alex, family_id: FAM#tracer}}. A deny would be 401/403.
# Also confirm a BAD token is rejected:
curl -s -o /dev/null -w "no-token HTTP %{{http_code}}\\n" {HTTP_API_URL}/tracer-iam
curl -s -o /dev/null -w "bad-token HTTP %{{http_code}}\\n" -H "Authorization: Bearer not-a-real-token" {HTTP_API_URL}/tracer-iam
""")

    print("=" * 72)
    print("STEP B — Bedrock seam (one real Converse tool-use call):")
    print("=" * 72)
    print(f"""curl -s -X POST -H "Authorization: Bearer {token}" \\
  -H "content-type: application/json" \\
  -d '{{"text":"Sam is blocked on the taxes and they are due by April 15."}}' \\
  {HTTP_API_URL}/tracer-bedrock | python3 -m json.tool
# Read back: stop_reason, tool_use_count, multiple_tool_uses_in_one_turn,
# tools_chosen, chosen_member_ids, enum_respected. THESE ARE THE §3.5 FINDINGS.
""")

    print("=" * 72)
    print("STEP C — WebSocket seam (connect, receive the hard-coded post-back):")
    print("=" * 72)
    print(f"""# $connect is UNAUTHENTICATED in the tracer (WS auth is Session-6); it only
# proves the post-back loop. with websocat (brew install websocat):
websocat -1 "{WS_URL}"
# OR with wscat (npm i -g wscat):  wscat -c "{WS_URL}"
# Expect one message pushed on connect: {{"entity":"work_item","id":"WI#tracer","op":"updated"}}
""")


if __name__ == "__main__":
    main()
