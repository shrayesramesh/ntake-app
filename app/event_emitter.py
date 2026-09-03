from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
    async def emit(self, entity: str, id: int, op: str) -> None:
class EventEmitter(ABC):
    @abstractmethod
    async def emit(self, entity: str, id: int, op: str) -> None:
        """Emit a change event with entity type, ID, and operation."""
        pass
            await listener(entity, id, op)
class InProcessEmitter(EventEmitter):
    def __init__(self):
        self.listeners = []

    async def emit(self, entity: str, id: int, op: str) -> None:
        for listener in self.listeners:
            await listener(entity, id, op)

    def add_listener(self, listener):
        self.listeners.append(listener)