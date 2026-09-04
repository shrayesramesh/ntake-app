"""The ``fake`` assistant backend — deterministic, no model (dev/tests).

Parallel to the ``local_llm`` package: both implement the two seams from
``app.assistant.base`` (:class:`CaptureResolver`, :class:`AssistantClient`) and
are selected by ``NTAKE_ASSISTANT`` via ``app.assistant.factory``. Swapping
backends is a config flip; this package is the reference implementation to read
alongside the local-LLM one.
"""

from __future__ import annotations

from app.assistant.fake.assistant import FakeAssistant
from app.assistant.fake.resolver import FakeCaptureResolver

__all__ = ["FakeAssistant", "FakeCaptureResolver"]
