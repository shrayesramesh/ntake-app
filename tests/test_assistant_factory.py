"""Phase 4 — the config-driven assistant factory."""

from __future__ import annotations

from app.assistant.factory import get_assistant


def test_default_is_fake(monkeypatch):
    monkeypatch.delenv("NTAKE_ASSISTANT", raising=False)
    from app.assistant.fake import FakeAssistant as Fake

    assert isinstance(get_assistant(), Fake)


def test_off_is_null(monkeypatch):
    from app.assistant.base import NullAssistant

    monkeypatch.setenv("NTAKE_ASSISTANT", "off")
    a = get_assistant()
    assert isinstance(a, NullAssistant)
    # NullAssistant proposes nothing regardless of input.
    from datetime import UTC, datetime

    from app.assistant.base import CaptureContext

    ctx = CaptureContext(
        text="friday", work_item_id=1, timezone="UTC", now=datetime.now(UTC)
    )
    assert a.propose(ctx) == []


def test_ollama_falls_back_to_fake_until_implemented(monkeypatch):
    from app.assistant.fake import FakeAssistant as Fake

    monkeypatch.setenv("NTAKE_ASSISTANT", "ollama")
    assert isinstance(get_assistant(), Fake)
