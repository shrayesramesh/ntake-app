"""⚠️ THROWAWAY tracer WebSocket handlers (Session 1.5). ⚠️

Exercises the **WebSocket** seam (AWS_HLD §8, AWS_LLD §4): the API-GW → ``$connect``
path. On ``$connect`` the handler writes the connection to the tracer table and
returns 200. It does **not** post back on connect — Session 1.5 found that posting
to the connecting socket from inside ``$connect`` hangs and fails (the connection
isn't established yet; an API Gateway quirk). The real design never does that:
nudges are posted from the confirm/execute boundary — a separate invocation to
already-established connections (AWS_LLD §4.2) — validated in Session 6/8. So the
tracer proves connect + routing + handshake + the connection write; delivery to a
listening client is deferred to the correct seam.

In the tracer, ``$connect`` is **unauthenticated** (no custom authorizer): gating
the connect is a Session-6 concern (and WS authorizers have no simple-response
mode). So there is no authorizer ``context`` here — the connection item uses a
fixed ``FAM#tracer`` family id.

The pure ``nudge`` shaper (the ``{entity,id,op}`` shape the real publisher will
send) is gate-tested; the ``connect``/``disconnect`` handlers are deployed-only
(need boto3).
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
    """``$connect`` — store the connection item. Does NOT post back on connect.

    Session 1.5 finding: posting to the *connecting* socket from inside ``$connect``
    does **not** work — the connection isn't fully established yet, so
    ``post_to_connection`` hangs (~7s, observed) and fails. This is an API Gateway
    WebSocket quirk, and the real design never does it: live-sync nudges are posted
    from the **confirm/execute boundary** — a *separate* invocation to
    *already-established* connections (AWS_LLD §4.2) — which is the reliable path,
    validated in Session 6/8. So the tracer only proves connect + routing +
    handshake + the connection write here; the ``nudge()`` shape ships for the real
    publisher to use. Delivery-to-a-listening-client is deferred to Session 6/8
    (where it is wired at the correct seam).
    """
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
