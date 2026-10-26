"""The authorizer Lambda shell — both response shapes it must emit (§5.2).

One authorizer Lambda serves both APIs, and they require different outputs:

* **HTTP API (payload 2.0)** — the *simple* response ``{isAuthorized, context}``.
* **WebSocket ``$connect``** — WebSocket APIs don't support simple responses; the
  authorizer must return an **IAM policy** (``principalId`` + ``policyDocument``
  allowing ``execute-api:Invoke`` on the ``methodArn``) plus ``context``.
  Returning the simple shape there makes API Gateway answer the handshake with a
  500 — the bug the live-nudge Tier-2 test caught.

The shell is driven with the real AWS event shapes over the in-memory
``TokenStore`` (the ``_runtime`` adapters are swapped for in-memory ones).
"""

from __future__ import annotations

from typing import Any

import pytest

from core.identity import mint_device_token
from core.token_store_memory import InMemoryTokenStore
from handlers import _runtime, authorizer

SECRET = "install-secret"
METHOD_ARN = "arn:aws:execute-api:us-east-1:111037110464:abc123/dev/$connect"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> InMemoryTokenStore:
    mem = InMemoryTokenStore()
    monkeypatch.setattr(_runtime, "token_store", lambda: mem)
    monkeypatch.setattr(_runtime, "token_secret", lambda: SECRET)
    return mem


def _plaintext(store: InMemoryTokenStore) -> str:
    return mint_device_token(
        store, family_id="fam1", member_id="m1", role="adult", label="", secret=SECRET
    ).plaintext


def _http_event(token: str | None) -> dict[str, Any]:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return {
        "version": "2.0",
        "type": "REQUEST",
        "routeArn": "arn:aws:execute-api:us-east-1:111037110464:xyz/$default/GET/board",
        "headers": headers,
    }


def _ws_event(token: str | None) -> dict[str, Any]:
    return {
        "type": "REQUEST",
        "methodArn": METHOD_ARN,
        "headers": {},
        "queryStringParameters": {"token": token} if token else {},
        "requestContext": {"eventType": "CONNECT", "routeKey": "$connect"},
    }


_CONTEXT = {"member_id": "m1", "family_id": "fam1", "role": "adult"}


# --- HTTP API: simple response ----------------------------------------------


def test_http_allow_is_a_simple_response(store: InMemoryTokenStore) -> None:
    out = authorizer.handler(_http_event(_plaintext(store)))
    assert out == {"isAuthorized": True, "context": _CONTEXT}


def test_http_deny_is_a_simple_response(store: InMemoryTokenStore) -> None:
    assert authorizer.handler(_http_event("bogus")) == {"isAuthorized": False}


# --- WebSocket $connect: IAM policy response --------------------------------


def _statement(out: dict[str, Any]) -> dict[str, Any]:
    statements = out["policyDocument"]["Statement"]
    assert len(statements) == 1
    stmt: dict[str, Any] = statements[0]
    return stmt


def test_ws_allow_is_an_iam_policy_with_context(store: InMemoryTokenStore) -> None:
    out = authorizer.handler(_ws_event(_plaintext(store)))
    assert "isAuthorized" not in out
    assert out["principalId"] == "m1"
    assert out["policyDocument"]["Version"] == "2012-10-17"
    assert _statement(out) == {
        "Action": "execute-api:Invoke",
        "Effect": "Allow",
        "Resource": METHOD_ARN,
    }
    assert out["context"] == _CONTEXT


def test_ws_deny_is_an_iam_deny_policy(store: InMemoryTokenStore) -> None:
    out = authorizer.handler(_ws_event("bogus"))
    assert _statement(out)["Effect"] == "Deny"
    assert _statement(out)["Resource"] == METHOD_ARN
    assert "context" not in out


def test_ws_missing_token_is_denied(store: InMemoryTokenStore) -> None:
    assert _statement(authorizer.handler(_ws_event(None)))["Effect"] == "Deny"
