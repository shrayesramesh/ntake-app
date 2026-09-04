"""Phase 4 / task 7 — the config-in-code assistant seams (stage 1 + 2 factories).

Selection is a typed ``AssistantConfig`` value passed IN (no env vars, no module
globals): the factory is a pure map from config → seam instances. ``fake``
(default) and ``off`` use the deterministic backend; ``local`` builds the
LLM-backed classes over a ``LocalLlmClient`` from the config's model/url/timeout.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.capture import FocusedContext, NullAssistant
from app.assistant.factory import (
    AssistantConfig,
    default_assistant_config,
    get_assistant,
    get_capture_resolver,
)
from app.assistant.fake import FakeAssistant, FakeCaptureResolver
from app.assistant.local_llm.assistant import LocalLlmAssistant
from app.assistant.local_llm.resolver import LocalLlmCaptureResolver


def _cfg(kind: str) -> AssistantConfig:
    return AssistantConfig(kind=kind)


# --- the default is code, not env -----------------------------------------


def test_default_config_is_fake():
    assert default_assistant_config().kind == "fake"


# --- stage 2: get_assistant ------------------------------------------------


def test_fake_config_gives_fake_assistant():
    assert isinstance(get_assistant(_cfg("fake")), FakeAssistant)


def test_off_config_gives_null_assistant():
    a = get_assistant(_cfg("off"))
    assert isinstance(a, NullAssistant)
    ctx = FocusedContext(
        text="friday",
        timezone="UTC",
        now=datetime.now(UTC),
        resolved_work_item_ids=[1],
    )
    assert a.propose(ctx) == []


def test_local_config_gives_local_llm_assistant():
    assert isinstance(get_assistant(_cfg("local")), LocalLlmAssistant)


# --- stage 1: get_capture_resolver (same config switch) --------------------


def test_fake_config_gives_fake_resolver():
    assert isinstance(get_capture_resolver(_cfg("fake")), FakeCaptureResolver)


def test_off_config_still_uses_fake_resolver():
    # 'off' disables stage-2 proposing only; the endpoint still needs a resolver
    # to build a FocusedContext, so stage 1 stays the fake.
    assert isinstance(get_capture_resolver(_cfg("off")), FakeCaptureResolver)


def test_local_config_gives_local_llm_resolver():
    assert isinstance(get_capture_resolver(_cfg("local")), LocalLlmCaptureResolver)


# --- the local client is built from the config knobs -----------------------


def test_local_client_carries_config_url_model_timeout():
    cfg = AssistantConfig(
        kind="local",
        model="qwen2.5:14b",
        base_url="http://localhost:11434",
        timeout=90.0,
    )
    resolver = get_capture_resolver(cfg)
    assert isinstance(resolver, LocalLlmCaptureResolver)
    client = resolver._llm  # the injected LLM seam is the httpx client
    assert client._base_url == "http://localhost:11434"
    assert client._model == "qwen2.5:14b"
    assert client._timeout == 90.0


def test_config_defaults_are_the_llamafile_reference_runtime():
    cfg = default_assistant_config()
    assert cfg.base_url == "http://localhost:8080"
    assert cfg.model == "llama3.1:8b"
    # local path needs a much larger timeout than the fake (cold start + 2 calls).
    assert cfg.timeout >= 60.0
