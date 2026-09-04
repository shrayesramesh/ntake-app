"""The ``local_llm`` assistant backend — a live local model behind the two seams.

Parallel to the ``fake`` package: both implement the two seams from
``app.assistant.base`` (:class:`CaptureResolver`, :class:`AssistantClient`) and
are selected by ``AssistantConfig.kind`` via ``app.assistant.factory``. This backend
talks to a localhost model server over an OpenAI-style JSON HTTP call (llamafile
is the reference runtime; Ollama / LM Studio / llama-server expose the same seam).

Task 7 Track A builds this package incrementally, TDD, with **no model running**:
the transport is abstracted behind the :class:`LLM` protocol (``protocol.py``) so
every layer above it tests against the :class:`ScriptedLLM` double. Only
``client.py`` (a later step) imports httpx.
"""

from __future__ import annotations

from app.assistant.local_llm.protocol import LLM, ScriptedLLM

__all__ = ["LLM", "ScriptedLLM"]
