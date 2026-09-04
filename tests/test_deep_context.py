"""deep_context.py — LINK ids → validated → deep context for the PROPOSE call.

The LINK LLM returns ``{"work_item_ids": [...], "event_ids": [...]}``. These tests
cover: tolerant parsing of that (untrusted) JSON; server-side **validation**
(whitelist to the member's family — the "never invent an id" rule enforced, not
just asked); the **member footprint** union (the capturing member's assigned work
items are always included, even if the note didn't link them); the rendered deep
context (a member header + each work item WITH its full update history + linked
events).

NOTE (flagged in the LLD): "events the member participates in" is deferred — the
Event model has no ``participants`` column yet. Member footprint here = assigned
work items; linked events still appear by id.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.deep_context import deep_context, parse_ids, resolve_ids
from app.models import Event, WorkItem, WorkItemUpdate

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _wi(session, family_id, title, **kw):
    wi = WorkItem(
        family_id=family_id, title=title, created_at=NOW, updated_at=NOW, **kw
    )
    session.add(wi)
    session.commit()
    return wi


def _update(session, work_item_id, author_id, body, source="human"):
    u = WorkItemUpdate(
        work_item_id=work_item_id,
        author_id=author_id,
        source=source,
        body=body,
        created_at=NOW,
    )
    session.add(u)
    session.commit()
    return u


def _event(session, family_id, title, **kw):
    ev = Event(
        family_id=family_id,
        title=title,
        start_at=kw.pop("start_at", datetime(2026, 9, 5, 19, 0, tzinfo=UTC)),
        created_at=NOW,
        updated_at=NOW,
        **kw,
    )
    session.add(ev)
    session.commit()
    return ev


# --- parse_ids: tolerant of untrusted model JSON --------------------------


def test_parse_ids_extracts_int_lists():
    wi, ev, mem = parse_ids(
        {"work_item_ids": [1, 2], "event_ids": [8], "member_ids": [1]}
    )
    assert wi == [1, 2] and ev == [8] and mem == [1]


def test_parse_ids_tolerates_missing_keys_and_junk():
    wi, ev, mem = parse_ids({"work_item_ids": [3, "x", None, 4.0], "note": "ignored"})
    assert wi == [3]  # non-ints dropped (4.0 is not an int)
    assert ev == []  # missing key -> empty
    assert mem == []  # missing member_ids -> empty


def test_parse_ids_handles_empty_or_bad_input():
    assert parse_ids({}) == ([], [], [])
    assert parse_ids({"work_item_ids": "nope"}) == ([], [], [])


def test_parse_ids_coerces_prefixed_and_string_tokens():
    # A small model tends to echo the world-view TOKENS ("w3"/"e8"/"m1") — the
    # exact labels it was shown — often as strings, instead of bare ints. Accept
    # those (and plain numeric strings) by coercing to the int; the id is what
    # matters.
    wi, ev, mem = parse_ids(
        {"work_item_ids": ["w3", "5"], "event_ids": ["e8", 2], "member_ids": ["m1"]}
    )
    assert wi == [3, 5]
    assert ev == [8, 2]
    assert mem == [1]


def test_parse_ids_coercion_is_case_insensitive_on_the_prefix():
    wi, ev, mem = parse_ids(
        {"work_item_ids": ["W3"], "event_ids": ["E8"], "member_ids": ["M1"]}
    )
    assert wi == [3] and ev == [8] and mem == [1]


def test_parse_ids_rejects_wrong_or_bad_prefix_tokens():
    # An event token under work_item_ids (and vice versa) is NOT accepted — the
    # prefix must match the list. Non-numeric junk after the prefix is dropped.
    wi, ev, mem = parse_ids(
        {"work_item_ids": ["e1", "wx", "w"], "event_ids": ["w2", "eNaN"]}
    )
    assert wi == []  # "e1" wrong prefix; "wx"/"w" no digits
    assert ev == []  # "w2" wrong prefix; "eNaN" no digits
    assert mem == []


# --- validation: whitelist to the member's family -------------------------


def test_deep_context_drops_unknown_and_foreign_ids(session, fam_member):
    fam, m = fam_member
    mine = _wi(session, fam.id, "my task")
    # an unknown id and a foreign-family id must not appear.
    from app.models import Family

    other = Family(name="Other", timezone="UTC")
    session.add(other)
    session.commit()
    foreign = _wi(session, other.id, "foreign task")

    out = deep_context(session, m, [mine.id, foreign.id, 9999], [])
    assert "my task" in out
    assert "foreign task" not in out  # foreign-family id dropped
    # (9999 unknown -> silently dropped; no crash)


# --- member footprint: assigned items always included ---------------------


def test_deep_context_includes_members_assigned_items(session, fam_member):
    fam, m = fam_member
    _wi(session, fam.id, "assigned to me", assigned_to=m.id)
    # note linked NOTHING, but the member's own assigned item still shows up.
    out = deep_context(session, m, [], [])
    assert "assigned to me" in out


def test_deep_context_unions_linked_and_footprint_without_dup(session, fam_member):
    fam, m = fam_member
    both = _wi(session, fam.id, "linked and mine", assigned_to=m.id)
    # linked by id AND assigned to the member -> appears exactly once.
    out = deep_context(session, m, [both.id], [])
    assert out.count("linked and mine") == 1


def test_deep_context_excludes_other_members_assigned_items(session, fam_member):
    fam, m = fam_member
    from app.models import Member

    other = Member(family_id=fam.id, display_name="Sam", role="child", created_at=NOW)
    session.add(other)
    session.commit()
    _wi(session, fam.id, "sams task", assigned_to=other.id)
    out = deep_context(session, m, [], [])
    assert "sams task" not in out  # not this member's footprint, not linked


# --- rendering: member header + full update history + events --------------


def test_deep_context_has_member_header(session, fam_member):
    _fam, m = fam_member
    out = deep_context(session, m, [], [])
    assert m.display_name in out  # whose context this is


def test_deep_context_renders_timed_events_in_the_family_timezone(session, fam_member):
    """Stored UTC datetimes must not conflict with the family-time prompt frame."""
    fam, m = fam_member
    ev = _event(
        session,
        fam.id,
        "Dentist",
        start_at=datetime(2026, 9, 4, 21, 37, tzinfo=UTC),
        end_at=datetime(2026, 9, 4, 22, 37, tzinfo=UTC),
    )

    out = deep_context(session, m, [], [ev.id])

    assert "Dentist — Fri Sep 4, 5:37 PM – Fri Sep 4, 6:37 PM" in out
    assert "9:37 PM" not in out


def test_deep_context_renders_full_update_history(session, fam_member):
    fam, m = fam_member
    wi = _wi(session, fam.id, "call plumber", assigned_to=m.id)
    _update(session, wi.id, m.id, "left a voicemail")
    _update(session, wi.id, m.id, "they will call back", source="assistant")
    out = deep_context(session, m, [wi.id], [])
    assert "left a voicemail" in out
    assert "they will call back" in out  # the WHOLE log, both sources


def test_deep_context_renders_linked_events(session, fam_member):
    fam, m = fam_member
    ev = _event(session, fam.id, "Dentist")
    out = deep_context(session, m, [], [ev.id])
    assert "Dentist" in out


def test_deep_context_keeps_work_item_context_before_event_context(session, fam_member):
    fam, m = fam_member
    wi = _wi(session, fam.id, "Call plumber", assigned_to=m.id)
    _update(session, wi.id, m.id, "Left a voicemail")
    ev = _event(session, fam.id, "Dentist")

    out = deep_context(session, m, [wi.id], [ev.id])

    assert out.index("RELEVANT WORK ITEMS:") < out.index("RELEVANT EVENTS:")
    assert out.index("Left a voicemail") < out.index("Dentist")


def test_deep_context_includes_member_participated_events(session, fam_member):
    fam, m = fam_member
    # member participates (linked member_id) -> included in footprint even though
    # the note linked no events.
    _event(session, fam.id, "Soccer", participants=[{"member_id": m.id}])
    out = deep_context(session, m, [], [])
    assert "Soccer" in out


def test_deep_context_excludes_events_member_does_not_participate_in(
    session, fam_member
):
    fam, m = fam_member
    _event(session, fam.id, "Someone elses meeting", participants=[{"name": "Guest"}])
    out = deep_context(session, m, [], [])
    assert "Someone elses meeting" not in out


def test_deep_context_dedups_linked_and_participated_event(session, fam_member):
    fam, m = fam_member
    ev = _event(session, fam.id, "Shared game", participants=[{"member_id": m.id}])
    # linked by id AND participated -> appears exactly once.
    out = deep_context(session, m, [], [ev.id])
    assert out.count("Shared game") == 1


def test_deep_context_renders_linked_members(session, fam_member):
    fam, m = fam_member
    from app.models import Member

    sam = Member(family_id=fam.id, display_name="Sam", role="adult", created_at=NOW)
    session.add(sam)
    session.commit()
    # The note linked Sam (member_ids=[sam.id]); the deep context must surface
    # Sam so PROPOSE can attribute the action to them.
    out = deep_context(session, m, [], [], [sam.id])
    assert "Sam" in out
    assert f"m{sam.id}" in out


def test_deep_context_empty_when_nothing_linked_or_assigned(session, fam_member):
    fam, m = fam_member
    out = deep_context(session, m, [], [])
    # still a string with the member header, just no items/events sections filled.
    assert isinstance(out, str) and m.display_name in out


# --- resolve_ids: whitelist untrusted linked ids to the family ------------


def test_resolve_ids_keeps_only_family_ids_preserving_order(session, fam_member):
    fam, m = fam_member
    a = _wi(session, fam.id, "a")
    b = _wi(session, fam.id, "b")
    ev = _event(session, fam.id, "party")

    from app.models import Family

    other = Family(name="Other", timezone="UTC")
    session.add(other)
    session.commit()
    foreign = _wi(session, other.id, "foreign")

    # Model returned two valid ids (out of order), a foreign id, and an unknown
    # id; only the family's survive, in the given order.
    wi_ids, ev_ids, mem_ids = resolve_ids(
        session, m, [b.id, 9999, foreign.id, a.id], [ev.id, 8888], []
    )
    assert wi_ids == [b.id, a.id]
    assert ev_ids == [ev.id]
    assert mem_ids == []


def test_resolve_ids_whitelists_members_to_family(session, fam_member):
    fam, m = fam_member
    from app.models import Family, Member

    sam = Member(family_id=fam.id, display_name="Sam", role="adult", created_at=NOW)
    session.add(sam)
    other = Family(name="Other", timezone="UTC")
    session.add(other)
    session.commit()
    stranger = Member(
        family_id=other.id, display_name="Stranger", role="adult", created_at=NOW
    )
    session.add(stranger)
    session.commit()

    # m (the capturer) + sam are family; stranger is foreign; 7777 unknown.
    _wi_ids, _ev_ids, mem_ids = resolve_ids(
        session, m, [], [], [m.id, stranger.id, sam.id, 7777]
    )
    assert mem_ids == [m.id, sam.id]  # order preserved, foreign/unknown dropped


def test_resolve_ids_empty_in_empty_out(session, fam_member):
    _fam, m = fam_member
    assert resolve_ids(session, m, [], [], []) == ([], [], [])
