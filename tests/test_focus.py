"""Stage 1 — CaptureResolver.focus(): CaptureRequest -> FocusedContext (DB lookups),
plus render_focus and how the FakeAssistant stamps it onto proposals.

The ``CaptureResolver`` seam is the app-coupled resolver: it queries the DB and
produces the *focused world* stage 2 reasons over. ``FakeCaptureResolver`` (v1)
does NOT resolve a target work item from free text (that's a v2/Ollama
capability), so ``work_item_id`` is always None. It DOES populate
``calendar_window`` with the family's events as id-bearing ``EventSummary``
objects — the ids are what make stage-2 proposals executable against real events.

``render_focus`` is a readable print of the focused context; the FakeAssistant
stamps it verbatim onto each proposal's ``llm_rationale`` (pass-through, no
intelligence). A real assistant (Ollama) writes a genuine description there.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.assistant.base import CaptureResolver
from app.assistant.context import (
    CaptureRequest,
    EventSummary,
    FocusedContext,
    render_focus,
)
from app.assistant.fake import FakeAssistant, FakeCaptureResolver
from app.manage import seed_event
from app.models import Family, Member

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _fam_member(session):
    fam = Family(name="F", timezone="America/New_York")
    session.add(fam)
    session.commit()
    m = Member(family_id=fam.id, display_name="A", role="adult", created_at=NOW)
    session.add(m)
    session.commit()
    return fam, m


def _req(text="hello") -> CaptureRequest:
    return CaptureRequest(text=text, timezone="America/New_York", now=NOW)


def test_focus_returns_focused_context_passing_through_raw_fields(session):
    fam, m = _fam_member(session)
    ctx = FakeCaptureResolver().focus(_req("call plumber"), session, m)
    assert isinstance(ctx, FocusedContext)
    assert ctx.text == "call plumber"
    assert ctx.timezone == "America/New_York"
    assert ctx.now == NOW


def test_focus_work_item_id_is_none_in_v1(session):
    fam, m = _fam_member(session)
    ctx = FakeCaptureResolver().focus(
        _req("the plumber item, he's coming friday"), session, m
    )
    # v1: no text-based target resolution yet.
    assert ctx.work_item_id is None


def test_focus_populates_calendar_window_with_event_summaries(session):
    fam, m = _fam_member(session)
    ev = seed_event(
        session,
        fam.id,
        title="Soccer",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
    )
    ctx = FakeCaptureResolver().focus(_req(), session, m)
    assert len(ctx.calendar_window) == 1
    summary = ctx.calendar_window[0]
    assert isinstance(summary, EventSummary)
    assert summary.id == ev.id  # id-bearing, so stage 2 can target it
    assert summary.title == "Soccer"
    assert summary.all_day is False
    assert summary.start is not None


def test_focus_includes_all_day_events(session):
    fam, m = _fam_member(session)
    seed_event(
        session, fam.id, title="Holiday", all_day=True, start_date=date(2026, 12, 25)
    )
    ctx = FakeCaptureResolver().focus(_req(), session, m)
    s = ctx.calendar_window[0]
    assert s.all_day is True
    assert s.start_date == date(2026, 12, 25)
    assert s.start is None


def test_focus_scopes_calendar_window_to_the_members_family(session):
    fam, m = _fam_member(session)
    other = Family(name="Other", timezone="UTC")
    session.add(other)
    session.commit()
    seed_event(
        session,
        other.id,
        title="NotMine",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
    )
    seed_event(
        session,
        fam.id,
        title="Mine",
        start_at=datetime(2026, 9, 6, 19, 0, tzinfo=UTC),
    )
    ctx = FakeCaptureResolver().focus(_req(), session, m)
    titles = [s.title for s in ctx.calendar_window]
    assert titles == ["Mine"]


def test_focus_empty_calendar_is_empty_window(session):
    fam, m = _fam_member(session)
    ctx = FakeCaptureResolver().focus(_req(), session, m)
    assert ctx.calendar_window == []


# --- the CaptureResolver seam contract ------------------------------------


def test_fake_capture_resolver_is_a_capture_resolver():
    assert isinstance(FakeCaptureResolver(), CaptureResolver)


def test_capture_resolver_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        CaptureResolver()  # type: ignore[abstract]


# --- render_focus + FakeAssistant rationale stamping ----------------------


def _ctx(text: str, window=None, target_id=None) -> FocusedContext:
    return FocusedContext(
        text=text,
        work_item_id=target_id,
        timezone="America/New_York",
        now=NOW,
        calendar_window=window or [],
    )


def test_render_focus_includes_text_and_event_titles():
    ctx = _ctx(
        "dentist appointment friday",
        window=[EventSummary(id=1, title="Soccer", start=NOW)],
    )
    out = render_focus(ctx)
    assert "dentist appointment friday" in out
    assert "Soccer" in out  # event titles are surfaced, not a count
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
