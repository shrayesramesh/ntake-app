#!/usr/bin/env python3
"""First-device bootstrap — mint a pairing code (or token) for a family (§5.3).

The break-glass path: there's no enrolled adult yet to create a pairing code, so
this is run **once per family** by an operator with AWS creds. It writes directly
to the real table via the Dynamo ``TokenStore`` (no deployed admin Lambda — that
is deferred; this script is the simpler v1 bootstrap, per the owner's call to
avoid the cumbersome admin-Lambda invoke dance).

Default output is a **6-digit pairing code** so even bootstrap uses the same
"type the code on the device" flow as everyday enrollment — the new device
exchanges it at ``POST /pair`` for its token. Pass ``--token`` to instead mint a
device token directly and print the plaintext once (e.g. for a headless kiosk).

Usage (from ntake-aws/, with AWS creds for the target account):
    .venv/bin/python scripts/mint.py --family FAM_ULID --member MEM_ULID \
        [--role adult|child] [--label "Mom's phone"] [--token]

Env: NTAKE_TABLE_NAME (default ntake-dev), NTAKE_REGION (default us-east-1),
     NTAKE_TOKEN_SECRET_ID (default ntake-<stage>/token-secret).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boto3

from adapters.dynamo_token_store import DynamoTokenStore
from core.identity import create_pairing_code, mint_device_token


def _region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


def _table_name() -> str:
    return os.environ.get("NTAKE_TABLE_NAME", "ntake-dev")


def _token_secret() -> str:
    stage = os.environ.get("NTAKE_STAGE", "dev")
    secret_id = os.environ.get("NTAKE_TOKEN_SECRET_ID", f"ntake-{stage}/token-secret")
    raw = boto3.client("secretsmanager", region_name=_region()).get_secret_value(
        SecretId=secret_id
    )["SecretString"]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    return str(parsed.get("secret", raw)) if isinstance(parsed, dict) else raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a device for a family.")
    parser.add_argument("--family", required=True, help="family ULID (prefix-free)")
    parser.add_argument("--member", required=True, help="member ULID (prefix-free)")
    parser.add_argument("--role", default="adult", choices=["adult", "child"])
    parser.add_argument("--label", default="", help="human device label")
    parser.add_argument(
        "--token",
        action="store_true",
        help="mint a device token directly (print plaintext once) instead of a code",
    )
    args = parser.parse_args(argv)

    store = DynamoTokenStore(_table_name(), region_name=_region())

    if args.token:
        minted = mint_device_token(
            store,
            family_id=args.family,
            member_id=args.member,
            role=args.role,
            label=args.label,
            secret=_token_secret(),
        )
        print("Device token (shown ONCE — store it on the device now):")
        print(f"  {minted.plaintext}")
    else:
        code = create_pairing_code(
            store,
            family_id=args.family,
            member_id=args.member,
            role=args.role,
            label=args.label,
        )
        print("Pairing code (type it on the new device within 10 minutes):")
        print(f"  {code.code}")
        print(f"  expires_at: {code.expires_at.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
