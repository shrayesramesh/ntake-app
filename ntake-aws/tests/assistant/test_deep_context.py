"""``deep_context`` + ``resolve_ids`` — behaviour-faithful to the reference.

The PROPOSE-stage input (git show main:app/assistant/context/deep.py): validate
LINK's ids to the family (validate-don't-trust), then render a narrow/deep text
block — the linked work items with their FULL update history + checklist, plus
each footprint member's assigned items and participated events. Pins the exact
rendered string; implementation is free.

Adaptations the AWS rebuild forces (behaviour-preserving): reads via the
``Repository`` seam (``get_work_item``/``get_event``/``get_member``/
``list_work_items``/``list_events``); updates + checklist come off the co-located
``WorkItem`` aggregate; ids are ULID strings rendered as ``[w:<id>]`` /
``[e:<id>]`` / ``[m:<id>]`` (Option A). Updates order by ``(created_at,
update_id)``; checklist by ``position``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from core.assistant.deep import deep_context, resolve_ids
from core.repository_memory import InMemoryRepository
from core.schemas import (
    ChecklistEntry,
    Event,
    Family,
    Member,
    WorkItem,
    WorkItemUpdate,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _fam() -> Family:
    return Family(id="fam1", name="Test", timezone=TZ, created_at=NOW)


def _member(mid: str, name: str = "Alex", role: str = "adult") -> Member:
    return Member(
        id=mid, family_id="fam1", display_name=name, role=role, created_at=NOW
    )


def _dt(mon: int, day: int, hour: int) -> datetime:
    return datetime(2026, mon, day, hour, 0, tzinfo=UTC)


def _upd(uid: str, src: str, body: str, when: datetime) -> WorkItemUpdate:
    return WorkItemUpdate(
        update_id=uid, author_id=None, source=src, body=body, created_at=when
    )


def _wi(wid: str, title: str, status: str = "todo", **kw: object) -> WorkItem:
    return WorkItem(
        id=wid,
        family_id="fam1",
        title=title,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        **kw,  # type: ignore[arg-type]
    )


def _repo(members: list[Member]) -> InMemoryRepository:
    repo = InMemoryRepository()
    repo.seed_family(_fam(), members)
    return repo


# --- resolve_ids (validate-don't-trust) ------------------------------------


def test_resolve_ids_drops_ids_not_in_family() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w1", "real"))
    wi, ev, mem = resolve_ids(
        repo, alex, ["w1", "w_bogus"], ["e_bogus"], ["m1", "m_bogus"]
    )
    assert wi == ["w1"]
    assert ev == []
    assert mem == ["m1"]


def test_resolve_ids_preserves_order() -> None:
    alex = _member("m1")
    repo = _repo([alex, _member("m2", "Sam", "child")])
    resolved = resolve_ids(repo, alex, [], [], ["m2", "m1"])[2]
    assert resolved == ["m2", "m1"]


# --- deep_context rendering ------------------------------------------------


def test_deep_context_renders_linked_work_item_full_detail() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    wi = _wi(
        "w1",
        "call plumber",
        "doing",
        description="leaky sink",
        due_at=_dt(9, 5, 19),
        tags=["home", "urgent"],
        checklist=[
            ChecklistEntry(text="get quote", checked=True, position=0),
            ChecklistEntry(text="book date", checked=False, position=1),
        ],
        updates=[
            _upd("u1", "human", "called, no answer", _dt(9, 1, 14)),
            _upd("u2", "assistant", "flagged blocked", _dt(9, 2, 9)),
        ],
    )
    repo.put_work_item(wi)

    out = deep_context(repo, alex, ["w1"], [], [])

    expected = (
        "RELEVANT WORK ITEMS:\n"
        "- [w:w1] call plumber (doing, due Sat Sep 5, 3:00 PM) [tags: home, urgent]\n"
        "    DESCRIPTION: leaky sink\n"
        "    CHECKLIST:\n"
        "    · [x] get quote\n"
        "    · [ ] book date\n"
        "    UPDATES:\n"
        "    · [human · Tue Sep 1, 10:00 AM] called, no answer\n"
        "    · [assistant · Wed Sep 2, 5:00 AM] flagged blocked\n"
        "\n"
        "RELEVANT EVENTS:\n"
        "- (none)"
    )
    assert out == expected


def test_deep_context_also_about_header_for_linked_other_member() -> None:
    alex, sam = _member("m1"), _member("m2", "Sam", "child")
    repo = _repo([alex, sam])
    out = deep_context(repo, alex, [], [], ["m2"])
    assert out.startswith("ALSO ABOUT: [m:m2] Sam (child)\n")


def test_deep_context_no_also_about_for_author_only() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    out = deep_context(repo, alex, [], [], ["m1"])
    assert "ALSO ABOUT" not in out


def test_deep_context_folds_in_assigned_items_of_footprint_member() -> None:
    alex, sam = _member("m1"), _member("m2", "Sam", "child")
    repo = _repo([alex, sam])
    repo.put_work_item(_wi("w5", "sam's chore", assigned_to="m2"))
    # Note links Sam (no work item linked directly) → Sam's assigned item appears.
    out = deep_context(repo, alex, [], [], ["m2"])
    assert "- [w:w5] sam's chore (todo)" in out


def test_deep_context_folds_in_participated_events_by_name() -> None:
    alex, sam = _member("m1"), _member("m2", "Sam", "child")
    repo = _repo([alex, sam])
    repo.put_event(
        Event(
            id="e3",
            family_id="fam1",
            title="Recital",
            all_day=False,
            start_at=_dt(9, 6, 18),
            end_at=_dt(9, 6, 19),
            participants=["Sam"],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    out = deep_context(repo, alex, [], [], ["m2"])
    assert "- [e:e3] Recital —" in out


def test_deep_context_empty_renders_none_sections() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    out = deep_context(repo, alex, [], [], [])
    assert out == "RELEVANT WORK ITEMS:\n- (none)\n\nRELEVANT EVENTS:\n- (none)"


# --- complex situations (port-regression edges) ---------------------------


def test_dedup_work_item_both_linked_and_assigned_appears_once_linked_first() -> None:
    # w1 is linked directly AND assigned to the author → one render, linked-first.
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w1", "shared", assigned_to="m1"))
    repo.put_work_item(_wi("w2", "author other", assigned_to="m1"))
    out = deep_context(repo, alex, ["w1"], [], [])
    # w1 appears exactly once, and before the purely-assigned w2.
    assert out.count("- [w:w1] shared") == 1
    assert out.index("[w:w1]") < out.index("[w:w2]")


def test_dedup_event_both_linked_and_participated_appears_once() -> None:
    alex = _member("m1", "Alex")
    repo = _repo([alex])
    repo.put_event(
        Event(
            id="e1",
            family_id="fam1",
            title="Meeting",
            all_day=False,
            start_at=_dt(9, 5, 15),
            end_at=_dt(9, 5, 16),
            participants=["Alex"],  # author participates AND it's linked
            created_at=NOW,
            updated_at=NOW,
        )
    )
    out = deep_context(repo, alex, [], ["e1"], [])
    assert out.count("- [e:e1] Meeting") == 1


def test_author_own_assigned_items_fold_in_without_any_linked_member() -> None:
    # The author is always in the footprint, so their assigned items appear even
    # when the note links nobody.
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w1", "alex task", assigned_to="m1"))
    out = deep_context(repo, alex, [], [], [])
    assert "- [w:w1] alex task (todo)" in out


def test_excludes_non_footprint_members_assigned_items() -> None:
    # Sam is NOT linked (not in footprint) → Sam's item must not appear.
    alex, sam = _member("m1"), _member("m2", "Sam", "child")
    repo = _repo([alex, sam])
    repo.put_work_item(_wi("w9", "sam only", assigned_to="m2"))
    out = deep_context(repo, alex, [], [], [])
    assert "sam only" not in out


def test_updates_render_in_created_at_order_despite_input_order() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    wi = _wi(
        "w1",
        "task",
        updates=[
            _upd("u2", "human", "second", _dt(9, 2, 9)),  # inserted first…
            _upd("u1", "human", "first", _dt(9, 1, 9)),  # …but earlier timestamp
        ],
    )
    repo.put_work_item(wi)
    out = deep_context(repo, alex, ["w1"], [], [])
    assert out.index("] first") < out.index("] second")


def test_omits_empty_checklist_and_updates_headers() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w1", "bare", description="only a desc"))
    out = deep_context(repo, alex, ["w1"], [], [])
    assert "DESCRIPTION: only a desc" in out
    assert "CHECKLIST:" not in out
    assert "UPDATES:" not in out


def test_all_day_event_with_tags_in_deep_context() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_event(
        Event(
            id="e1",
            family_id="fam1",
            title="Trip",
            all_day=True,
            start_date=date(2026, 9, 5),
            end_date=date(2026, 9, 5),
            tags=["travel"],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    out = deep_context(repo, alex, [], ["e1"], [])
    assert "- [e:e1] Trip — Sat Sep 5 (all day) [tags: travel]" in out


def test_timed_event_start_equals_end_collapses() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_event(
        Event(
            id="e1",
            family_id="fam1",
            title="Point",
            all_day=False,
            start_at=_dt(9, 5, 15),
            end_at=_dt(9, 5, 15),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    out = deep_context(repo, alex, [], ["e1"], [])
    assert "- [e:e1] Point — Sat Sep 5, 11:00 AM" in out
    assert "–" not in out


def test_participant_match_is_case_and_whitespace_insensitive() -> None:
    alex = _member("m1")
    sam = _member("m2", "Sam", "child")
    repo = _repo([alex, sam])
    repo.put_event(
        Event(
            id="e1",
            family_id="fam1",
            title="Recital",
            all_day=False,
            start_at=_dt(9, 6, 18),
            end_at=_dt(9, 6, 19),
            participants=["  sAm  "],  # messy casing + whitespace still matches "Sam"
            created_at=NOW,
            updated_at=NOW,
        )
    )
    out = deep_context(repo, alex, [], [], ["m2"])
    assert "- [e:e1] Recital —" in out


def test_participant_match_does_not_false_match_different_name() -> None:
    alex = _member("m1")
    sam = _member("m2", "Sam", "child")
    repo = _repo([alex, sam])
    repo.put_event(
        Event(
            id="e1",
            family_id="fam1",
            title="Samantha's party",
            all_day=False,
            start_at=_dt(9, 6, 18),
            end_at=_dt(9, 6, 19),
            participants=["Samantha"],  # NOT "Sam"
            created_at=NOW,
            updated_at=NOW,
        )
    )
    out = deep_context(repo, alex, [], [], ["m2"])
    assert "Samantha's party" not in out


def test_resolve_ids_dedups_duplicate_input_ids() -> None:
    # Dedup at the source: a duplicate resolved id is meaningless and must not
    # ride on FocusedContext into PROPOSE's enum-over-whitelist (improves on the
    # reference, which left dups in and relied on the render to dedup).
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w1", "dup task"))
    wi, _ev, _mem = resolve_ids(repo, alex, ["w1", "w1"], [], [])
    assert wi == ["w1"]  # resolve dedups
    out = deep_context(repo, alex, wi, [], [])
    assert out.count("- [w:w1] dup task") == 1
