"""Lambda REQUEST authorizer — device-token → allow + member context (§5.2).

A thin shell: extract the presented token (Bearer header, or ``?token=`` for the
WebSocket ``$connect``), resolve it through the tested ``_auth.authorize`` logic
over the real ``TokenStore``, and return the HTTP API **simple-response** shape
(``{isAuthorized, context}`` — the format the Session-1.5 tracer proved correct,
not an IAM policy document). The resolved ``{member_id, family_id, role}`` is
passed to the handlers as authorizer context, so handlers never re-resolve the
token.
"""

from __future__ import annotations

from typing import Any

from handlers import _runtime
from handlers._auth import authorize, extract_token


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """HTTP API simple-response authorizer entry point."""
    token = extract_token(
        authorization_header=_header(event, "authorization"),
        query_token=_query(event, "token"),
    )
    decision = authorize(_runtime.token_store(), token, secret=_runtime.token_secret())
    if not decision.allowed or decision.principal is None:
        return {"isAuthorized": False}
    p = decision.principal
    return {
        "isAuthorized": True,
        "context": {"member_id": p.member_id, "family_id": p.family_id, "role": p.role},
    }


def _header(event: dict[str, Any], name: str) -> str | None:
    """A request header (HTTP API lowercases header keys)."""
    headers = event.get("headers") or {}
    return headers.get(name) or headers.get(name.title())


def _query(event: dict[str, Any], name: str) -> str | None:
    """A query-string param (used by the WebSocket ``$connect`` ``?token=``)."""
    params = event.get("queryStringParameters") or {}
    return params.get(name)
