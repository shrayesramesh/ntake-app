"""Checkpoint 1e — SSE subscription wiring.

The 1d seam (commit → publish) is proven in test_write_seam.py. The SSE endpoint
is thin transport over :func:`app.main.subscribe`, so we test that unit directly:
a change published to the emitter lands on a subscriber's queue, formatted as the
SSE message the client receives. No socket / ASGI stream — the endpoint's
``while True`` never completes, so unit-testing the wiring is both simpler and
avoids a hanging test. Real `EventSource` reachability is the manual 1f smoke.
"""

from __future__ import annotations

import json

import pytest

from app.event_emitter import InProcessEmitter
from app.main import _format_change, subscribe


def test_format_change_shape():
    msg = _format_change("events", 7, "create")
    assert msg["event"] == "change"
    assert json.loads(msg["data"]) == {"entity": "events", "id": 7, "op": "create"}


@pytest.mark.asyncio
async def test_subscribe_receives_emitted_change():
    emitter = InProcessEmitter()
    queue, unsubscribe = subscribe(emitter)

    await emitter.emit("families", 3, "update")

    assert queue.get_nowait() == ("families", 3, "update")

    # Unsubscribing detaches the listener so later emits are not received.
    unsubscribe()
    await emitter.emit("families", 4, "create")
    assert queue.empty()
