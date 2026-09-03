"""Change-event seam (checkpoint 1d).

On any write, the backend publishes a change event ``{entity, id, op}`` to an
in-process emitter; the SSE endpoint (1e) will subscribe and stream these to
connected clients. Keeping this a small, tested unit lets the HLD's "writes emit
change events" behavior exist independently of the transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

Listener = Callable[[str, int, str], Awaitable[None]]


class EventEmitter(ABC):
    """Abstract change-event emitter."""

    @abstractmethod
    async def emit(self, entity: str, id: int, op: str) -> None:
        """Emit a change event with entity type, ID, and operation."""


class InProcessEmitter(EventEmitter):
    """Simple in-process fan-out to registered async listeners."""

    def __init__(self) -> None:
        self.listeners: list[Listener] = []

    async def emit(self, entity: str, id: int, op: str) -> None:
        for listener in self.listeners:
            await listener(entity, id, op)

    def add_listener(self, listener: Listener) -> None:
        self.listeners.append(listener)
