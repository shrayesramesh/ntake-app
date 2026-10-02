"""⚠️ THROWAWAY tracer authorizer (Session 1.5). ⚠️

A REQUEST Lambda authorizer that proves the device-token → member path on the
deployed slice. It reuses the **real** lifted ``core.tokens.hash_token``
(AWS_LLD §5.1) — that is the one genuinely-exercised production seam here — but
everything around it (the DynamoDB token-store, the IAM policy shape) is minimal
scaffolding, replaced by the real authorizer in Session 6.

Design for testability: the decision is a **pure function** (``authorize``) that
takes the presented token, the HMAC secret, and a ``lookup`` callable
(hash → token record | None). The Lambda ``handler`` is a thin shell that wires
the real secret (Secrets Manager, injected via env for the tracer) and a real
DynamoDB ``GetItem`` lookup around that pure core, so the allow/deny logic is
unit-tested under ``make check`` with no AWS.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from core.tokens import hash_token

# A token record is whatever the store returns; the tracer only needs the ids and
# the revocation flag. Kept as a plain dict (not a DTO) — this is scaffolding.
TokenRecord = dict[str, Any]
Lookup = Callable[[str], TokenRecord | None]


def _policy(effect: str, principal_id: str, method_arn: str) -> dict[str, Any]:
    """A minimal API-GW authorizer IAM policy document (allow or deny)."""
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": method_arn,
                }
            ],
        },
    }


def authorize(
    token: str | None,
    *,
    secret: str,
    lookup: Lookup,
    method_arn: str,
) -> dict[str, Any]:
    """Pure allow/deny decision for a presented device token.

    Hashes ``token`` with the real :func:`core.tokens.hash_token`, looks the hash
    up via ``lookup``, and returns an API-GW authorizer response. A missing token,
    an unknown hash, or a revoked record all deny — indistinguishably (as the real
    design intends, AWS_LLD §5.2). On allow, the member/family ids ride back in the
    authorizer ``context`` so a handler never re-resolves the token.
    """
    if not token:
        return _policy("Deny", "anonymous", method_arn)

    record = lookup(hash_token(token, secret=secret))
    if record is None or record.get("revoked_at"):
        return _policy("Deny", "anonymous", method_arn)

    member_id = str(record.get("member_id", ""))
    allow = _policy("Allow", member_id or "member", method_arn)
    allow["context"] = {
        "member_id": member_id,
        "family_id": str(record.get("family_id", "")),
    }
    return allow


def _extract_token(event: dict[str, Any]) -> str | None:
    """Pull the bearer token from an HTTP ``Authorization`` header or ``?token=``.

    Mirrors the real dual accommodation (AWS_LLD §5.2/§5.4): REST sends
    ``Authorization: Bearer <t>``; the WebSocket ``$connect`` can only pass
    ``?token=`` at connect time.
    """
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[len("bearer ") :].strip()
    params = event.get("queryStringParameters") or {}
    token = params.get("token")
    return token.strip() if token else None


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """Lambda entry point — thin shell around :func:`authorize` (deployed-only).

    Wires the real secret (``NTAKE_TOKEN_SECRET`` env, set by CDK from the Secrets
    Manager secret) and a real DynamoDB ``GetItem`` lookup. Excluded from coverage:
    it only runs in the deployed slice; the decision logic it delegates to is what
    the local tests cover.
    """
    import boto3

    secret = os.environ["NTAKE_TOKEN_SECRET"]
    table_name = os.environ["TRACER_TABLE_NAME"]
    table = boto3.resource("dynamodb").Table(table_name)

    def lookup(token_hash: str) -> TokenRecord | None:
        resp = table.get_item(Key={"pk": f"TOK#{token_hash}", "sk": "#META"})
        return resp.get("Item")

    method_arn = event.get("methodArn") or event.get("routeArn") or "*"
    return authorize(
        _extract_token(event),
        secret=secret,
        lookup=lookup,
        method_arn=method_arn,
    )
