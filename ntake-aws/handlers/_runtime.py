"""Lambda runtime wiring — build the real adapters from the environment.

The thin shells call these to assemble the ``boto3``-backed adapters the tested
handler logic depends on, reading config from the Lambda environment (set by CDK
from the stage props — the one legitimate deploy-time env use). Kept apart from
the logic so the logic stays pure/Tier-1-testable; this module is the only
handler code that touches ``boto3`` + the environment.

Env (set by CDK): ``NTAKE_TABLE_NAME``, ``NTAKE_REGION`` (or ``AWS_REGION``),
``NTAKE_TOKEN_SECRET_ID`` (Secrets Manager id of the HMAC token secret),
``NTAKE_ANTHROPIC_MODEL``, ``NTAKE_WS_ENDPOINT`` (the API Gateway Management API
endpoint for ``postToConnection``).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

import boto3

from adapters.anthropic_http import HttpAnthropicClient
from adapters.dynamo_repository import DynamoRepository
from adapters.dynamo_token_store import DynamoTokenStore
from core.assistant.anthropic_client import AnthropicClient
from core.live_sync import ConnectionPoster


def _region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


def _table_name() -> str:
    return os.environ["NTAKE_TABLE_NAME"]


def repository() -> DynamoRepository:
    """The family repository over the real table."""
    return DynamoRepository(_table_name(), region_name=_region())


def token_store() -> DynamoTokenStore:
    """The identity store (device tokens + pairing codes) over the real table."""
    return DynamoTokenStore(_table_name(), region_name=_region())


def anthropic_client() -> AnthropicClient:
    """The real Anthropic Messages client (capture path only)."""
    model = os.environ.get("NTAKE_ANTHROPIC_MODEL", "claude-haiku-4-5")
    return HttpAnthropicClient(model=model, region_name=_region())


@lru_cache(maxsize=1)
def token_secret() -> str:
    """The per-install HMAC token secret, read once from Secrets Manager + cached.

    The authorizer and the pairing exchange hash tokens under this secret
    (AWS_LLD §5.1). Stored as a JSON ``{"secret": "..."}`` or a bare string; both
    are accepted.
    """
    secret_id = os.environ["NTAKE_TOKEN_SECRET_ID"]
    raw = boto3.client("secretsmanager", region_name=_region()).get_secret_value(
        SecretId=secret_id
    )["SecretString"]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if isinstance(parsed, dict):
        return str(parsed.get("secret", raw))
    return raw


def connection_poster() -> ConnectionPoster:
    """A ``postToConnection`` poster over the API Gateway Management API.

    Returns ``True`` on delivery, ``False`` when the socket is gone (410 →
    ``GoneException``) so ``publish_change`` prunes it. Other transport errors
    propagate and are swallowed by ``publish_change`` per socket.
    """
    endpoint = os.environ["NTAKE_WS_ENDPOINT"]
    client = boto3.client(
        "apigatewaymanagementapi", endpoint_url=endpoint, region_name=_region()
    )

    def _post(connection_id: str, data: str) -> bool:
        try:
            client.post_to_connection(
                ConnectionId=connection_id, Data=data.encode("utf-8")
            )
            return True
        except client.exceptions.GoneException:
            return False

    return _post
