"""Tier-2: write → publish → live WebSocket nudge, end to end on dev (Session 6).

The Session-6 Tier-2 exit (AWS_PLAN): the deployed stack serves real routes
through the **real authorizer with a real device token**, and a confirmed write
posts a live WebSocket nudge to a listening client — the server→client delivery
the Session-1.5 tracer deferred to this boundary (AWS_LLD §4.2).

Flow, all against the deployed ``NtakeStack-dev``:
1. seed an ``itest-`` family + member into the real table;
2. mint a device token in-process (the token secret from Secrets Manager +
   ``DynamoTokenStore``) — nothing is read from the operator's environment;
3. open the WebSocket with ``?token=`` (exercises the WS authorizer + the
   ``$connect`` handler registering the connection);
4. ``POST /work-items`` (Bearer token → the HTTP authorizer Lambda + the writes
   Lambda) → expect ``{"entity":"work_item","id":<id>,"op":"create"}`` on the
   socket;
5. ``POST /actions/confirm`` ``complete_work_item`` on that item → expect the
   ``update`` nudge.

Cleanup: family/member/work-item/connection rows are ``FAM#itest-…`` (swept by
the integration conftest); the ``TOK#`` token item is deleted here explicitly.
Self-skips cleanly if the stack outputs or the token secret aren't set up —
never a false pass.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import boto3
import pytest

import tests.harness.factories as factories
from adapters.dynamo_repository import DynamoRepository
from adapters.dynamo_token_store import DynamoTokenStore
from core.identity import MintedToken, mint_device_token
from core.token_store import token_pk
from tests.harness.ws_client import ReceiveOnlyWebSocket, WebSocketClosed

_STACK = os.environ.get("NTAKE_STACK_NAME", "NtakeStack-dev")
_TOKEN_SECRET_ID = "ntake-dev/token-secret"


def _region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


def _table_name() -> str:
    return os.environ.get("NTAKE_TABLE_NAME", "ntake-dev")


@pytest.fixture(scope="module")
def stack_urls() -> tuple[str, str]:
    """(HttpApiUrl, WsApiUrl) from the deployed stack's outputs."""
    try:
        cfn = boto3.client("cloudformation", region_name=_region())
        outputs = cfn.describe_stacks(StackName=_STACK)["Stacks"][0].get("Outputs", [])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"{_STACK} not describable ({type(e).__name__}) — [HUMAN] deploy.")
    by_key = {o["OutputKey"]: o["OutputValue"] for o in outputs}
    if "HttpApiUrl" not in by_key or "WsApiUrl" not in by_key:
        pytest.skip(f"{_STACK} lacks HttpApiUrl/WsApiUrl outputs — [HUMAN] deploy.")
    return by_key["HttpApiUrl"].rstrip("/"), by_key["WsApiUrl"].rstrip("/")


@pytest.fixture(scope="module")
def token_secret() -> str:
    """The HMAC token secret the deployed authorizer hashes under."""
    try:
        raw = boto3.client("secretsmanager", region_name=_region()).get_secret_value(
            SecretId=_TOKEN_SECRET_ID
        )["SecretString"]
    except Exception as e:  # noqa: BLE001
        pytest.skip(
            f"{_TOKEN_SECRET_ID} unreadable ({type(e).__name__}) — "
            "run `make secrets-token` [HUMAN]."
        )
    parsed = json.loads(raw)
    return str(parsed["secret"]) if isinstance(parsed, dict) else raw


@pytest.fixture
def minted(
    dynamo_repo: DynamoRepository, token_secret: str
) -> Iterator[tuple[MintedToken, str]]:
    """Seed an itest family + member and mint a real device token for them."""
    family = factories.make_family(timezone="America/New_York")
    alex = factories.make_member(family.id, display_name="Alex")
    dynamo_repo.seed_family(family, [alex])
    store = DynamoTokenStore(_table_name(), region_name=_region())
    token = mint_device_token(
        store,
        family_id=family.id,
        member_id=alex.id,
        role="adult",
        label="itest nudge",
        secret=token_secret,
    )
    try:
        yield token, family.id
    finally:
        # TOK# items aren't under FAM#itest-, so the conftest sweep misses them.
        dynamo_repo._table.delete_item(
            Key={"PK": token_pk(token.record.token_hash), "SK": "#META"}
        )


def _post(url: str, token: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(  # noqa: S310 — the deployed dev API
        url,
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _next_nudge(ws: ReceiveOnlyWebSocket) -> dict[str, Any]:
    message = ws.receive_text()
    print(f"\n[ws nudge] {message}")
    parsed: dict[str, Any] = json.loads(message)
    return parsed


def test_write_and_confirm_post_live_websocket_nudges(
    stack_urls: tuple[str, str], minted: tuple[MintedToken, str]
) -> None:
    http_url, ws_url = stack_urls
    token, _family_id = minted

    ws = ReceiveOnlyWebSocket(f"{ws_url}?token={token.plaintext}", timeout=20)
    try:
        # A direct REST write → the authorizer resolves the real token, the
        # writes Lambda persists + announces → this socket gets the nudge.
        status, created = _post(
            f"{http_url}/work-items", token.plaintext, {"title": "itest nudge"}
        )
        assert status == 201, created
        assert _next_nudge(ws) == {
            "entity": "work_item",
            "id": created["id"],
            "op": "create",
        }

        # The confirm/execute boundary → the same live nudge.
        status, result = _post(
            f"{http_url}/actions/confirm",
            token.plaintext,
            {
                "name": "complete_work_item",
                "target_id": created["id"],
                "target_type": "work_item",
            },
        )
        assert status == 200, result
        assert result["applied"] == "complete_work_item"
        assert _next_nudge(ws) == {
            "entity": "work_item",
            "id": created["id"],
            "op": "update",
        }
    finally:
        ws.close()


def test_websocket_refuses_an_unknown_token(stack_urls: tuple[str, str]) -> None:
    _http_url, ws_url = stack_urls
    # The WS authorizer denies → API GW refuses the upgrade (no 101).
    with pytest.raises(WebSocketClosed):
        ReceiveOnlyWebSocket(f"{ws_url}?token=not-a-real-token", timeout=10)
