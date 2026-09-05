"""Config-in-code selection of the assistant seams (Phase 4 / task 7).

The assistant's configuration is a typed, immutable **value** (:class:`AssistantConfig`)
constructed in code and passed IN to the factory — NOT read from ``os.environ`` here
and NOT a module global. The factory is a pure map from config → seam instances, so
tests inject a config directly (no env monkeypatching) and the app threads one
config through its dependency wiring.

This is the assistant's *infra* config, deliberately separate from
:class:`~app.config.FamilyConfig` (the out-of-repo ``family.toml`` — household PII
seeded into the DB). Two concerns, two configs: infra knobs live here with the
assistant; user/household data lives with the family config. Neither is a flat
mega-config.

``kind`` picks the implementation for BOTH capture stages: ``fake`` (default;
dev/tests), ``off`` (stage 2 = NullAssistant), or ``local`` (the live local LLM).
The ``local`` backend talks to a localhost model server over an OpenAI-style JSON
HTTP call (llamafile is the reference runtime; Ollama / LM Studio / llama-server
expose the same seam and differ only in ``base_url``/``model``), built from the
config knobs here — see ``app/assistant/local_llm/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.assistant.base import AssistantClient, CaptureResolver, NullAssistant
from app.assistant.fake import FakeAssistant, FakeCaptureResolver
from app.assistant.local_llm.client import LocalLlmClient
from app.assistant.local_llm.link import LocalLlmCaptureResolver
from app.assistant.local_llm.propose import LocalLlmAssistant

AssistantKind = Literal["fake", "off", "local"]


@dataclass(frozen=True)
class AssistantConfig:
    """The assistant's runtime (infra) configuration — a code value, not env/globals.

    ``kind`` selects the backend. The remaining fields configure the ``local``
    backend's ``LocalLlmClient`` (ignored by ``fake``/``off``): ``model`` and
    ``base_url`` are the runtime knobs (swapping llamafile → Ollama is just a
    different ``base_url``), and ``timeout`` is the per-call bound — much larger
    than the fake's, because the local path is two sequential model calls and the
    first after idle pays a cold-start load (the local path makes two calls).
    """

    kind: AssistantKind = "fake"
    model: str = "llama3.1:8b"
    base_url: str = "http://localhost:8080"  # llamafile reference runtime
    timeout: float = 120.0


def default_assistant_config() -> AssistantConfig:
    """The in-code default configuration (``fake`` backend). The app constructs
    its config here (or a variant) and threads it through; there is no ambient
    env/global to read."""
    return AssistantConfig()


def _local_client(config: AssistantConfig) -> LocalLlmClient:
    """Build the shared httpx LLM seam for the local backend from the config."""
    return LocalLlmClient(
        base_url=config.base_url, model=config.model, timeout=config.timeout
    )


def get_assistant(config: AssistantConfig) -> AssistantClient:
    """Stage 2: the config-selected ``AssistantClient`` (propose)."""
    if config.kind == "off":
        return NullAssistant()
    if config.kind == "local":
        return LocalLlmAssistant(_local_client(config))
    return FakeAssistant()


def get_capture_resolver(config: AssistantConfig) -> CaptureResolver:
    """Stage 1: the config-selected ``CaptureResolver`` (focus).

    Same ``kind`` switch as ``get_assistant``. ``off`` still needs a real resolver
    (the endpoint always builds a FocusedContext; only stage-2 proposing is
    disabled), so ``off`` uses the fake resolver; only ``local`` swaps in the
    LLM-backed one.
    """
    if config.kind == "local":
        return LocalLlmCaptureResolver(_local_client(config))
    return FakeCaptureResolver()
