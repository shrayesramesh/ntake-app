"""The assistant contracts — the two swappable seams, in one place.

This module homes the *interfaces* that the ``fake`` and ``local_llm`` packages
each implement, so a reader (or a new backend) has a single contract reference:

* **Stage 1 — :class:`CaptureResolver`**: resolve a raw ``CaptureRequest`` into a
  ``FocusedContext`` (the app-coupled, DB-touching stage). Defined here.
* **Stage 2 — :class:`AssistantClient`**: propose actions over a focused context
  (the engine-clean, session-free stage). Defined in the domain-agnostic engine
  (``app.routing``) and re-exported here alongside stage 1 so both contracts and
  the shared value types import from one spot.

The concrete backends live in parallel sub-packages selected by ``factory``:
``app.assistant.fake`` (dev/tests) and ``app.assistant.local_llm`` (host, task 7).
The app-specific capture *value types* stay in ``core.assistant.capture``; this
re-exports them too so a backend needs only ``from core.assistant.base import …``.
"""

# ⚠️ PARKED FOR SESSION 2 (AWS rebuild). The stage-1 ``CaptureResolver`` seam
# below still takes a SQLAlchemy ``Session`` and imports the deleted
# ``app.persistence.models`` (+ the old ``app.assistant.capture`` path). The
# stage-2 contract it re-exports (``AssistantClient``/``ProposedAction``) is
# already live in ``core.engine.engine`` and ``core.assistant.capture``; this
# module's own ``CaptureResolver`` is rewired to the ``Repository`` seam in
# Session 2 (AWS_LLD §2/§3), so it is excluded from the Session 1 gate. Old
# behavior: ``git show main:app/assistant/base.py``.

from __future__ import annotations

from abc import ABC, abstractmethod

from app.assistant.capture import (
    AssistantClient,
    CaptureRequest,
    FocusedContext,
    NullAssistant,
    ProposedAction,
)
from app.persistence.models import Member
from sqlalchemy.orm import Session

__all__ = [
    "AssistantClient",
    "CaptureRequest",
    "CaptureResolver",
    "FocusedContext",
    "NullAssistant",
    "ProposedAction",
]


class CaptureResolver(ABC):
    """Stage-1 seam: resolve a raw ``CaptureRequest`` into a ``FocusedContext``.

    A stateless, config-selected strategy (like ``AssistantClient``). The
    request-scoped DB ``session`` and the ``member`` flow in per call — they are
    NOT held on the resolver, so the resolver stays a singleton and the
    request-scoped session is never captured by a long-lived object. This is the
    **app-coupled** seam (it touches the DB), unlike the domain-agnostic engine;
    the ``FocusedContext`` it returns is the plain, session-free value object that
    crosses into stage 2. Concrete resolvers: ``FakeCaptureResolver`` (v1,
    deterministic) and (task 7) ``LocalLlmCaptureResolver`` (LLM-backed).
    """

    @abstractmethod
    def focus(
        self, request: CaptureRequest, session: Session, member: Member
    ) -> FocusedContext: ...
