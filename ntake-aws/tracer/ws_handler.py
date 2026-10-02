"""⚠️ THROWAWAY tracer WebSocket handlers (Session 1.5). ⚠️

Proves the **WebSocket** seam (AWS_HLD §8, AWS_LLD §4): the API-GW → authorizer →
``$connect`` → ``postToConnection`` loop. On ``$connect`` (authorized by the same
device-token authorizer via ``?token=``) the handler writes the connection to the
tracer table and **immediately posts back one hard-coded** ``{entity, id, op}``
nudge to the just-connected socket, so a client that connects receives a message
without any second request — the whole loop proven in one connect.

This is NOT the real live-sync design (that publishes from the confirm/execute
boundary, Session 6). It is the minimal post-back that proves the plumbing.

The pure ``nudge`` shaper is gate-tested; the ``connect``/``disconnect`` handlers
are deployed-only (need boto3 + the Management API endpoint).
"""

from __future__ import annotations

import json
from typing import Any

# The one hard-coded message the tracer posts back on connect — the §4 nudge
# shape ``{entity, id, op}`` the real client will refetch on.
HARDCODED_NUDGE = {"entity": "work_item", "id": "WI#tracer", "op": "updated"}


def nudge() -> str:
    """The hard-coded post-back payload, JSON-encoded (the §4 ``{entity,id,op}``)."""
    return json.dumps(HARDCODED_NUDGE)


def connect(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """``$connect`` — store the connection, then post the hard-coded nudge back."""
    import os

    import boto3

    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId", "")
    ctx = rc.get("authorizer", {})
    family_id = str(ctx.get("family_id", "FAM#tracer"))

    table = boto3.resource("dynamodb").Table(os.environ["TRACER_TABLE_NAME"])
    table.put_item(
        Item={
            "pk": family_id,
            "sk": f"CONN#{connection_id}",
            "member_id": str(ctx.get("member_id", "")),
        }
    )

    # Post the hard-coded nudge straight back to the connecting socket.
    domain = rc.get("domainName", "")
    stage = rc.get("stage", "")
    endpoint = f"https://{domain}/{stage}"
    mgmt = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)
    try:
        mgmt.post_to_connection(ConnectionId=connection_id, Data=nudge().encode())
    except Exception:  # noqa: BLE001 - a failed post must not fail the connect
        pass

    return {"statusCode": 200}


def disconnect(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """``$disconnect`` — drop the connection item (lazy cleanup, §4.2)."""
    import os

    import boto3

    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId", "")
    ctx = rc.get("authorizer", {})
    family_id = str(ctx.get("family_id", "FAM#tracer"))

    table = boto3.resource("dynamodb").Table(os.environ["TRACER_TABLE_NAME"])
    try:
        table.delete_item(Key={"pk": family_id, "sk": f"CONN#{connection_id}"})
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass
    return {"statusCode": 200}
