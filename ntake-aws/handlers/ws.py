"""WebSocket Lambda shells — ``$connect`` / ``$disconnect`` (AWS_LLD §4.1).

The channel is server→client nudges only (the client refetches; it never sends
over the socket), so there are no custom routes beyond connect/disconnect. On
``$connect`` the device is already authorized (the same REQUEST authorizer, via
``?token=``), so the resolved member context is on the event; we record the
connection under the family partition. ``$disconnect`` removes it. The actual
nudges are posted at the confirm/execute boundary (``publish_change``), not here.
"""

from __future__ import annotations

from typing import Any

from handlers import _runtime


def connect_handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """``$connect`` — record the connection under its family partition."""
    ctx = event.get("requestContext", {})
    connection_id = ctx.get("connectionId", "")
    authorizer = ctx.get("authorizer", {})
    family_id = authorizer.get("family_id")
    member_id = authorizer.get("member_id")
    if not (connection_id and family_id and member_id):
        return {"statusCode": 401}
    _runtime.repository().put_connection(family_id, connection_id, member_id)
    return {"statusCode": 200}


def disconnect_handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """``$disconnect`` — remove the connection (lazy cleanup also prunes gone ones)."""
    ctx = event.get("requestContext", {})
    connection_id = ctx.get("connectionId", "")
    authorizer = ctx.get("authorizer", {})
    family_id = authorizer.get("family_id")
    if connection_id and family_id:
        _runtime.repository().delete_connection(family_id, connection_id)
    return {"statusCode": 200}
