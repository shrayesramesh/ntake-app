"""Config-driven selection of the AssistantClient (Phase 4).

``NTAKE_ASSISTANT`` picks the implementation: ``fake`` (default; dev/tests),
``off`` (NullAssistant), or ``ollama`` (host — added in task 7). Keeping the
choice here means the rest of the app just calls ``get_assistant()``.
"""

from __future__ import annotations

import os

from app.assistant.base import AssistantClient, NullAssistant
from app.assistant.fake import FakeAssistant


def get_assistant() -> AssistantClient:
    kind = os.environ.get("NTAKE_ASSISTANT", "fake").lower()
    if kind == "off":
        return NullAssistant()
    if kind == "ollama":
        # Implemented in task 7 (host-only). Until then, fall back to fake so a
        # misconfigured dev box degrades to canned proposals rather than erroring.
        from app.assistant.fake import FakeAssistant as _Fallback

        return _Fallback()
    return FakeAssistant()
