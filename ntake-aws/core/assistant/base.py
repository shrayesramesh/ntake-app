"""The assistant contracts — the two swappable seams, in one place.

This module homes the *interfaces* the Anthropic-backed stages implement, so a
reader (or a new backend) has a single contract reference:

* **Stage 1 — :class:`CaptureResolver`**: resolve a raw ``CaptureRequest`` into a
  ``FocusedContext`` (the app-coupled, repository-touching stage). Defined here.
* **Stage 2 — :class:`AssistantClient`**: propose actions over a focused context
  (the engine-clean stage). Defined in the domain-agnostic engine
  (:mod:`core.engine.engine`) and re-exported here alongside stage 1 so both
  contracts and the shared value types import from one spot.

Session 3 port (AWS_LLD §2): stage 1's ``focus`` is rewired off the SQLAlchemy
``Session`` + ``app.persistence.models`` onto the
:class:`core.repository.Repository` seam + the lifted DTO ``Member``, and the
capture value types import from :mod:`core.assistant.capture` (the lifted home),
not the deleted ``app.assistant.capture``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.assistant.capture import (
    AssistantClient,
    CaptureRequest,
    FocusedContext,
    NullAssistant,
    ProposedAction,
)
from core.repository import Repository
from core.schemas import Member

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
    request-scoped ``repo`` and the ``member`` flow in per call — they are NOT
    held on the resolver, so the resolver stays a singleton. This is the
    **app-coupled** seam (it touches the repository), unlike the domain-agnostic
    engine; the ``FocusedContext`` it returns is the plain value object that
    crosses into stage 2. The concrete resolver is the LINK-backed
    :class:`core.assistant.anthropic_link.AnthropicCaptureResolver`.
    """

    @abstractmethod
    def focus(
        self, request: CaptureRequest, repo: Repository, member: Member
    ) -> FocusedContext: ...
