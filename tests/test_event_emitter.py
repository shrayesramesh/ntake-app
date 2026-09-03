import pytest

from app.event_emitter import InProcessEmitter


@pytest.mark.asyncio
async def test_emit():
    emitter = InProcessEmitter()
    received = []

    async def listener(entity, id, op):
        received.append((entity, id, op))

    emitter.add_listener(listener)

    await emitter.emit("event", 123, "create")

    assert received == [("event", 123, "create")]
