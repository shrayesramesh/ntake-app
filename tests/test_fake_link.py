"""Step 2 (WORKPLAN-A2) — the deterministic fake LINK.

``fake_link`` is the model-free analog of the pipeline's LINK call: it matches a
capture note against the family's non-archived work items and events by title,
case-insensitively, on *significant* title words (short words + stopwords are
ignored so "call the plumber" doesn't match every item with "the"). It returns
the matched ids (deduped, id-ordered). No LLM, fully deterministic.

These tests pin that contract: real matches resolve, noise words don't, archived
items and other families are excluded, and events match the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.fake.resolver import fake_link

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _link(session, family_id, note):
    return fake_link(session, family_id, note, NOW, TZ)


# --- work item matching ---------------------------------------------------


def test_matches_work_item_on_a_significant_title_word(
    session, fam_member, work_item_factory
):
    fam, m = fam_member
    wi = work_item_factory(fam.id, title="call plumber")
    wi_ids, ev_ids = _link(session, fam.id, "the plumber is coming friday")
    assert wi_ids == [wi.id]
    assert ev_ids == []


def test_no_match_when_note_shares_only_stopwords(
    session, fam_member, work_item_factory
):
    fam, m = fam_member
    work_item_factory(fam.id, title="call the plumber")
    # "the"/"is" are stopwords; "call" is < the matching set only via significant
    # words — the note shares no significant word ("plumber"/"call") here.
    wi_ids, _ = _link(session, fam.id, "we are done with everything")
    assert wi_ids == []


def test_matching_is_case_insensitive(session, fam_member, work_item_factory):
    fam, m = fam_member
    wi = work_item_factory(fam.id, title="Call Plumber")
    wi_ids, _ = _link(session, fam.id, "PLUMBER update")
    assert wi_ids == [wi.id]


def test_excludes_archived_work_items(session, fam_member, work_item_factory):
    fam, m = fam_member
    work_item_factory(fam.id, title="old plumber job", archived_at=NOW)
    wi_ids, _ = _link(session, fam.id, "plumber")
    assert wi_ids == []


def test_scopes_to_the_family(session, fam_member, family_factory, work_item_factory):
    fam, m = fam_member
    other = family_factory(name="Other")
    work_item_factory(other.id, title="plumber elsewhere")
    mine = work_item_factory(fam.id, title="plumber here")
    wi_ids, _ = _link(session, fam.id, "plumber")
    assert wi_ids == [mine.id]


def test_multiple_matches_are_deduped_and_id_ordered(
    session, fam_member, work_item_factory
):
    fam, m = fam_member
    a = work_item_factory(fam.id, title="buy milk")
    b = work_item_factory(fam.id, title="milk delivery")
    wi_ids, _ = _link(session, fam.id, "need milk")
    assert wi_ids == [a.id, b.id]


# --- event matching -------------------------------------------------------


def test_matches_events_by_title(session, fam_member, event_factory):
    fam, m = fam_member
    ev = event_factory(fam.id, title="Soccer practice")
    wi_ids, ev_ids = _link(session, fam.id, "when is soccer?")
    assert wi_ids == []
    assert ev_ids == [ev.id]


def test_no_ids_for_a_brand_new_capture(session, fam_member, work_item_factory):
    fam, m = fam_member
    work_item_factory(fam.id, title="call plumber")
    wi_ids, ev_ids = _link(session, fam.id, "buy stamps at the post office")
    assert wi_ids == []
    assert ev_ids == []
