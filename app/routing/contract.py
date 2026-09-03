"""Engine contract types — domain-agnostic (the reusable propose-confirm engine).

Imports NOTHING app-specific (no app.models, no sqlalchemy, no fastapi). This is
the shape a fallible model proposes against and the app dispatches on. Any
project can reuse it by registering its own actions + injecting its own opaque
context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ProposedAction:
    """A single proposed, unconfirmed action — exactly what an assistant returns.

    Domain-free: ``name`` is a registry key, ``params`` a plain dict. ``target_id``
    /``target_type`` identify what it operates on (opaque strings/ids to the
    engine). ``llm_rationale`` is the model's own narration (may be wrong/empty).
    There is deliberately no ``action_summary`` here — that is derived from the
    registry's ``describe`` (ground truth), not carried by the model.

    ``proposal_id`` is a batch-local handle assigned by the propose seam.
    ``target_ref`` is reserved for dependency chaining (a proposal targeting
    another proposal's to-be-created entity); unused in v1.
    """

    name: str
    params: dict
    llm_rationale: str = ""
    target_id: int | None = None
    target_type: str | None = None
    proposal_id: str = ""
    target_ref: str | None = None


class AssistantClient(ABC):
    """Proposes zero or more actions for an opaque context. MUST NOT mutate
    anything and MUST return [] on any failure (never raise into the request
    path). The engine treats ``ctx`` as opaque (``Any``) — it never inspects it;
    a concrete client may annotate its own context type."""

    @abstractmethod
    def propose(self, ctx: Any) -> list[ProposedAction]: ...


class NullAssistant(AssistantClient):
    """The 'off' client — never proposes anything."""

    def propose(self, ctx: Any) -> list[ProposedAction]:
        return []
