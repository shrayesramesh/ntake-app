"""Phase 4 — the config-driven assistant seams (stage 1 + stage 2 factories)."""

from __future__ import annotations

from app.assistant.factory import get_assistant, get_capture_resolver


def test_default_is_fake(monkeypatch):
    monkeypatch.delenv("NTAKE_ASSISTANT", raising=False)
    from app.assistant.fake import FakeAssistant as Fake

    assert isinstance(get_assistant(), Fake)


def test_off_is_null(monkeypatch):
    from app.assistant.context import NullAssistant

    monkeypatch.setenv("NTAKE_ASSISTANT", "off")
    a = get_assistant()
    assert isinstance(a, NullAssistant)
    # NullAssistant proposes nothing regardless of input.
    from datetime import UTC, datetime

    from app.assistant.context import FocusedContext

    ctx = FocusedContext(
        text="friday", timezone="UTC", now=datetime.now(UTC), resolved_work_item_ids=[1]
    )
    assert a.propose(ctx) == []


def test_ollama_falls_back_to_fake_until_implemented(monkeypatch):
    from app.assistant.fake import FakeAssistant as Fake

    monkeypatch.setenv("NTAKE_ASSISTANT", "ollama")
    assert isinstance(get_assistant(), Fake)


# --- stage 1: get_capture_resolver (same NTAKE_ASSISTANT switch) -----------


def test_capture_resolver_default_is_fake(monkeypatch):
    monkeypatch.delenv("NTAKE_ASSISTANT", raising=False)
    from app.assistant.fake import FakeCaptureResolver

    assert isinstance(get_capture_resolver(), FakeCaptureResolver)


def test_capture_resolver_off_still_uses_fake(monkeypatch):
    # 'off' disables stage-2 proposing only; the endpoint still needs a resolver
    # to build a FocusedContext, so stage 1 stays the fake.
    monkeypatch.setenv("NTAKE_ASSISTANT", "off")
    from app.assistant.fake import FakeCaptureResolver

    assert isinstance(get_capture_resolver(), FakeCaptureResolver)


def test_capture_resolver_ollama_falls_back_to_fake_until_implemented(monkeypatch):
    monkeypatch.setenv("NTAKE_ASSISTANT", "ollama")
    from app.assistant.fake import FakeCaptureResolver

    assert isinstance(get_capture_resolver(), FakeCaptureResolver)
