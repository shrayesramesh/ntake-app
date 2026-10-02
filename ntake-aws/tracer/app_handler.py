"""⚠️ THROWAWAY tracer HTTP handler (Session 1.5). ⚠️

Proves the **IAM** seam (AWS_HLD §11, AWS_LLD §8): a per-Lambda scoped role that
is granted read/write on exactly its own tracer table and nothing else. The
handler does a real DynamoDB ``PutItem`` + ``GetItem`` round trip, so a
mis-scoped role surfaces as ``AccessDenied`` on the deployed slice immediately —
the #1 first-deploy failure the tracer bullet exists to catch.

It also echoes the authorizer ``context`` (member/family ids) so the deployed
response confirms the authorizer→handler context pass-through end to end.

The pure ``ok``/``error`` response shapers are gate-tested; the ``handler``
itself is deployed-only (needs boto3 + a real table).
"""

from __future__ import annotations

import json
from typing import Any


def ok(payload: dict[str, Any]) -> dict[str, Any]:
    """A 200 JSON API-GW (HTTP API, payload v2) response."""
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload),
    }


def error(status: int, message: str) -> dict[str, Any]:
    """A non-200 JSON response carrying an error message."""
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"error": message}),
    }


def _authorizer_context(event: dict[str, Any]) -> dict[str, Any]:
    """Pull the member/family context the authorizer attached (HTTP API v2 shape)."""
    return event.get("requestContext", {}).get("authorizer", {}).get("lambda", {})


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """Lambda entry — a DynamoDB round trip proving the scoped role works."""
    import os
    import time

    import boto3

    table_name = os.environ["TRACER_TABLE_NAME"]
    table = boto3.resource("dynamodb").Table(table_name)

    ctx = _authorizer_context(event)
    marker = f"PING#{int(time.time() * 1000)}"
    try:
        table.put_item(Item={"pk": marker, "sk": "#META", "ok": True})
        got = table.get_item(Key={"pk": marker, "sk": "#META"}).get("Item")
    except Exception as exc:  # noqa: BLE001 - report IAM/other failure, don't raise
        return error(500, f"{type(exc).__name__}: {exc}")

    return ok(
        {
            "iam": "ok — scoped DynamoDB put+get succeeded",
            "round_tripped_item": got,
            "authorizer_context": ctx,
        }
    )
