"""Config-driven selection of the assistant seams (Phase 4).

``NTAKE_ASSISTANT`` picks the implementation for BOTH capture stages: ``fake``
(default; dev/tests), ``off`` (stage 2 = NullAssistant), or ``ollama`` (host —
added in task 7). One switch drives both stages so the app just calls
``get_assistant()`` (stage 2) and ``get_capture_resolver()`` (stage 1) without
knowing which backend is live.
"""

from __future__ import annotations

import os

from app.assistant.capture import CaptureResolver, FakeCaptureResolver
from app.assistant.context import AssistantClient, NullAssistant
from app.assistant.fake import FakeAssistant


def _kind() -> str:
    return os.environ.get("NTAKE_ASSISTANT", "fake").lower()


def get_assistant() -> AssistantClient:
    """Stage 2: the config-selected ``AssistantClient`` (propose)."""
    kind = _kind()
    if kind == "off":
        return NullAssistant()
    if kind == "ollama":
        # Implemented in task 7 (host-only). Until then, fall back to fake so a
        # misconfigured dev box degrades to canned proposals rather than erroring.
        return FakeAssistant()
    return FakeAssistant()


def get_capture_resolver() -> CaptureResolver:
    """Stage 1: the config-selected ``CaptureResolver`` (focus).

    Mirrors ``get_assistant`` and is driven by the same ``NTAKE_ASSISTANT``
    switch. ``off`` still needs a real resolver (the endpoint always builds a
    FocusedContext; only stage-2 proposing is disabled), so ``off`` and the
    not-yet-implemented ``ollama`` both use the fake for now.
    """
    if _kind() == "ollama":
        # Implemented in task 7 (host-only). Fall back to fake until then.
        return FakeCaptureResolver()
    return FakeCaptureResolver()
