"""Lambda REQUEST authorizer — device-token → allow + member context (§5.2).

One Lambda authorizes both APIs: extract the presented token (Bearer header, or
``?token=`` for the WebSocket ``$connect``), resolve it through the tested
``_auth.authorize`` logic over the real ``TokenStore``, and pass
``{member_id, family_id, role}`` to the handlers as authorizer context.

The two APIs need different response shapes:

* **HTTP API (payload 2.0)** — the simple response ``{isAuthorized, context}``.
* **WebSocket** — simple responses aren't supported; API Gateway requires an IAM
  policy (``principalId`` + ``policyDocument`` on the ``methodArn``) and answers
  any other shape with a 500. WebSocket authorizer events carry ``methodArn``
  (HTTP payload-2.0 events carry ``routeArn``), which selects the shape.
"""

from __future__ import annotations

from typing import Any

from handlers import _runtime
from handlers._auth import authorize, extract_token


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """Authorizer entry point for both the HTTP and the WebSocket API."""
    token = extract_token(
        authorization_header=(event.get("headers") or {}).get("authorization"),
        query_token=(event.get("queryStringParameters") or {}).get("token"),
    )
    decision = authorize(_runtime.token_store(), token, secret=_runtime.token_secret())
    p = decision.principal if decision.allowed else None
    ctx = (
        {"member_id": p.member_id, "family_id": p.family_id, "role": p.role}
        if p is not None
        else None
    )

    method_arn = event.get("methodArn")
    if method_arn is None:  # HTTP API payload 2.0: simple response
        if ctx is None:
            return {"isAuthorized": False}
        return {"isAuthorized": True, "context": ctx}

    policy: dict[str, Any] = {  # WebSocket: IAM policy response
        "principalId": p.member_id if p is not None else "anonymous",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": "Allow" if ctx else "Deny",
                    "Resource": method_arn,
                }
            ],
        },
    }
    if ctx:
        policy["context"] = ctx
    return policy
