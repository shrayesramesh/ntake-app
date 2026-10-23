"""Live-sync publish — the single server→client nudge boundary (AWS_LLD §4.2/§4.3).

When a confirmed write lands, every live device in the family is nudged with a
small ``{entity, id, op}`` message; the client refetches the affected data. This
module owns the **one** publish helper, ``publish_change``, called once at the
confirm/execute boundary (and the other write handlers) — the completeness
discipline that replaces DynamoDB Streams: every mutation flows through one place
that announces it (AWS_LLD §4.3, the single-publish-boundary invariant).

The actual delivery (API Gateway Management API ``postToConnection``) is an
**injected effect** — a ``ConnectionPoster`` the handler supplies — so ``core``
stays transport-free (no ``boto3``; the boundary test forbids it here). Tier-1
tests pass a fake poster and assert the fan-out; the Lambda supplies the real
``postToConnection`` poster.

Delivery is best-effort: a dead socket (the poster reporting a connection is
``gone``) is pruned via ``delete_connection``; any other poster error is swallowed
so a dead client never fails the user's confirmed write (AWS_LLD §4.2).
"""

from __future__ import annotations

import json
from typing import Protocol

from core.repository import Repository


class ConnectionPoster(Protocol):
    """The injected delivery effect: post one message to one connection.

    Returns ``True`` if delivered, ``False`` if the connection is gone (410) and
    should be pruned. Implementations must not raise for a gone connection — they
    report it; other transport errors may raise and are swallowed by the caller.
    """

    def __call__(self, connection_id: str, data: str) -> bool: ...


def publish_change(
    repo: Repository,
    family_id: str,
    entity: str,
    entity_id: str,
    op: str,
    *,
    poster: ConnectionPoster,
) -> None:
    """Nudge every live device in the family with ``{entity, id, op}`` (§4.2).

    The ONE publish call site (the confirm/execute boundary + the write handlers).
    Fans out over ``repo.list_connections(family_id)``; a connection the poster
    reports gone is pruned with ``delete_connection`` (lazy cleanup). Best-effort:
    a delivery error to one socket is swallowed so it never fails the write.
    """
    message = json.dumps({"entity": entity, "id": entity_id, "op": op})
    for connection_id in repo.list_connections(family_id):
        try:
            delivered = poster(connection_id, message)
        except Exception:  # noqa: BLE001 — a dead socket must not fail the write
            continue
        if not delivered:
            repo.delete_connection(family_id, connection_id)
