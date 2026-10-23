"""Tier-2: the deployed HTTP API routes through the real authorizer (Session 6).

Runs ONLY under ``make integration`` (Tier 1 ignores ``tests/integration``).
Proves the request path exists on the deployed ``NtakeStack-dev``: the public
routes serve without a token, and an authorized route denies without one — i.e.
the Lambda authorizer is actually wired. The authenticated capture→confirm→nudge
round trip needs a minted device token + a live WebSocket client; that fuller
exercise is the Session-8 end-to-end sweep. This smoke is the minimal
deployed-route assertion Session 6 can make.

Self-skips cleanly (never a false pass) if ``NtakeStack-dev`` isn't deployed or
has no HTTP API URL output yet — recorded as the [HUMAN] deploy follow-up.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import boto3
import pytest

_STACK = os.environ.get("NTAKE_STACK_NAME", "NtakeStack-dev")


def _region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture(scope="module")
def http_api_url() -> str:
    """The deployed HTTP API base URL from the stack's ``HttpApiUrl`` output."""
    try:
        cfn = boto3.client("cloudformation", region_name=_region())
        outputs = cfn.describe_stacks(StackName=_STACK)["Stacks"][0].get("Outputs", [])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"{_STACK} not describable ({type(e).__name__}) — [HUMAN] deploy.")
    url = next(
        (o["OutputValue"] for o in outputs if o["OutputKey"] == "HttpApiUrl"), None
    )
    if not url:
        pytest.skip(f"{_STACK} has no HttpApiUrl output — [HUMAN] deploy Session 6.")
    return url.rstrip("/")


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _post(url: str, body: bytes) -> tuple[int, str]:
    req = urllib.request.Request(  # noqa: S310
        url, data=body, headers={"content-type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_health_is_public_and_ok(http_api_url: str) -> None:
    status, body = _get(f"{http_api_url}/health")
    assert status == 200
    assert "ok" in body


def test_authorized_route_denies_without_a_token(http_api_url: str) -> None:
    # /board is behind the authorizer; no Authorization header → 401.
    status, _ = _get(f"{http_api_url}/board")
    assert status == 401


def test_pair_is_public_and_rejects_a_bogus_code(http_api_url: str) -> None:
    # /pair is public (no authorizer) but an unknown code is a clean 400 — proving
    # the route runs the pair handler, not the authorizer.
    status, body = _post(f"{http_api_url}/pair", b'{"code": "000000"}')
    assert status == 400
    assert "invalid pairing code" in body
