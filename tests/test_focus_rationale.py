"""The assistant describes what it understood: for the FakeAssistant, that is a
pass-through print of the FocusedContext, stamped onto each proposal's
llm_rationale (per-action — the card is self-describing). Real assistants
(Ollama) will write a genuine description here instead of a raw print.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.assistant.context import EventSummary, FocusedContext, render_focus
from app.assistant.fake import FakeAssistant

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _ctx(text: str, window=None, target_id=None) -> FocusedContext:
    return FocusedContext(
        text=text,
        work_item_id=target_id,
        timezone="America/New_York",
        now=NOW,
        calendar_window=window or [],
    )


# --- render_focus: a readable print of the focused context ----------------


def test_render_focus_includes_text_and_calendar_count():
    ctx = _ctx(
        "dentist appointment friday",
        window=[EventSummary(id=1, title="A", start=NOW)],
    )
    out = render_focus(ctx)
    assert "dentist appointment friday" in out
    assert "1" in out  # the calendar-window size is surfaced
    assert isinstance(out, str) and out


def test_render_focus_handles_empty_window():
    out = render_focus(_ctx("buy milk"))
    assert "buy milk" in out


def test_render_focus_handles_all_day_events():
    ctx = _ctx(
        "check",
        window=[
            EventSummary(
                id=2, title="Holiday", start_date=date(2026, 12, 25), all_day=True
            )
        ],
    )
    assert isinstance(render_focus(ctx), str)


# --- FakeAssistant stamps the focus print into each proposal --------------


def test_fake_stamps_focus_into_every_proposal_rationale():
    ctx = _ctx("dentist appointment friday")
    props = FakeAssistant().propose(ctx)
    expected = render_focus(ctx)
    assert props  # there is at least one proposal
    for p in props:
        assert p.llm_rationale == expected


def test_fake_focus_rationale_reflects_calendar_window():
    # Two overlapping events -> deconflict proposal; its rationale prints the
    # focused context, which mentions the calendar window.
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    window = [
        EventSummary(id=5, title="Soccer", start=start),
        EventSummary(id=8, title="Dentist", start=start),
    ]
    ctx = _ctx("check calendar", window=window)
    props = FakeAssistant().propose(ctx)
    dc = next(p for p in props if p.name == "deconflict_events")
    assert dc.llm_rationale == render_focus(ctx)
