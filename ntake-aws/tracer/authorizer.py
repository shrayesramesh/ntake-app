"""⚠️ THROWAWAY tracer authorizer (Session 1.5). ⚠️

A REQUEST Lambda authorizer that proves the device-token → member path on the
deployed slice. It reuses the **real** lifted ``core.tokens.hash_token``
(AWS_LLD §5.1) — the one genuinely-exercised production seam here — but everything
around it (the DynamoDB token-store, the response wiring) is minimal scaffolding,
replaced by the real authorizer in Session 6.

**Response format: HTTP API simple response (payload format 2.0).** The authorizer
returns ``{"isAuthorized": bool, "context": {...}}`` — NOT a hand-rolled IAM policy
document. Simple response is the easy, low-footgun path for an HTTP API custom
authorizer (an IAM-policy shape mismatch is a classic first-deploy failure that
silently fails open/closed). The tracer gates **only the HTTP API**; the WebSocket
``$connect`` is left unauthenticated in the tracer (it exists only to prove the
post-back loop — WS auth is a Session-6 concern, and WS authorizers have no simple
mode, so keeping it out of the tracer removes real complexity).

Design for testability: the decision is a **pure function** (``authorize``) taking
the token, the HMAC secret, and a ``lookup`` callable (hash → record | None). The
Lambda ``handler`` is a thin shell wiring the real secret + a DynamoDB ``GetItem``
lookup, so the allow/deny logic is unit-tested under ``make check`` with no AWS.
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


def authorize(token: str | None, *, secret: str, lookup: Lookup) -> dict[str, Any]:
    """Pure allow/deny decision for a presented device token (simple-response shape).

    Hashes ``token`` with the real :func:`core.tokens.hash_token`, looks the hash
    up via ``lookup``, and returns the HTTP API simple-response object. A missing
    token, an unknown hash, or a revoked record all deny — indistinguishably
    (AWS_LLD §5.2). On allow, the member/family ids ride back in ``context`` so a
    handler never re-resolves the token.
    """
    if not token:
        return {"isAuthorized": False}

    record = lookup(hash_token(token, secret=secret))
    if record is None or record.get("revoked_at"):
        return {"isAuthorized": False}

    return {
        "isAuthorized": True,
        "context": {
            "member_id": str(record.get("member_id", "")),
            "family_id": str(record.get("family_id", "")),
        },
    }


def _strip_bearer(value: str) -> str:
    """Return the token part of a value that may be ``Bearer <token>`` or bare."""
    if value.lower().startswith("bearer "):
        return value[len("bearer ") :].strip()
    return value.strip()


def _extract_token(event: dict[str, Any]) -> str | None:
    """Pull the bearer token from the shapes an HTTP API authorizer may present.

    HTTP API payload-format-2.0 REQUEST authorizers deliver the resolved identity
    source(s) in ``event.identitySource`` (a list). We also accept a raw
    ``Authorization`` header. First match wins.
    """
    identity = event.get("identitySource")
    if isinstance(identity, list) and identity:
        token = _strip_bearer(str(identity[0]))
        if token:
            return token

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization")
    if auth:
        token = _strip_bearer(auth)
        if token:
            return token
    return None


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:  # noqa: ARG001
    """Lambda entry point — thin shell around :func:`authorize` (deployed-only).

    Wires the real secret (``NTAKE_TOKEN_SECRET`` env, set by CDK from the Secrets
    Manager secret) and a real DynamoDB ``GetItem`` lookup, and returns the
    simple-response object the HTTP API (payload format 2.0) expects.
    """
    import boto3

    secret = os.environ["NTAKE_TOKEN_SECRET"]
    table_name = os.environ["TRACER_TABLE_NAME"]
    table = boto3.resource("dynamodb").Table(table_name)

    def lookup(token_hash: str) -> TokenRecord | None:
        resp = table.get_item(Key={"pk": f"TOK#{token_hash}", "sk": "#META"})
        return resp.get("Item")

    return authorize(_extract_token(event), secret=secret, lookup=lookup)
