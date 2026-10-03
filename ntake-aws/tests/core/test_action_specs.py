"""Spec-level tests — ``describe`` + ``render_card`` across the whole registry.

The ported specs (Session 3) carry two pure projections per action: ``describe``
(the deterministic action summary) and the optional ``render_card`` (the card's
detail lines). Both must tolerate missing/partial params (they run on
*unconfirmed* proposals) and never raise. This sweep exercises every registered
spec both ways — empty params and a representative filled set — which is the
cheap, DRY way to pin the summary/card surface without one test per function.
"""

from __future__ import annotations

import pytest

from core.actions.registry import ACTIONS

# A representative param set per action (filled enough to hit the "present" branch
# of each describe/render). Actions absent here are exercised with empty params.
_SAMPLE: dict[str, dict] = {
    "create_work_item": {
        "title": "Taxes",
        "description": "gather forms",
        "tags": ["finance"],
        "checklist_items": ["w2", "1099"],
    },
    "append_update": {"body": "called the vet"},
    "set_due_date": {"local_due_at": "2026-04-15T17:00"},
    "assign_work_item": {"member_id": "MEM#1"},
    "set_work_item_tags": {"tags": ["errand", "home"]},
    "add_checklist_items": {"items": ["milk", "eggs"]},
    "check_off_items": {"items": ["milk"]},
    "create_timed_event": {
        "title": "Dentist",
        "local_start_at": "2026-02-01T09:00",
        "location": "Main St",
        "description": "cleaning",
    },
    "create_all_day_event": {"title": "Trip", "start_date": "2026-03-01"},
    "reschedule_timed_event": {"local_start_at": "2026-02-02T09:00"},
    "reschedule_all_day_event": {"start_date": "2026-03-02"},
    "set_event_location": {"location": "Park"},
    "add_event_participants": {"participants": ["Alex", "Sam"]},
    "set_event_tags": {"tags": ["school"]},
}


@pytest.mark.parametrize("name", sorted(ACTIONS))
def test_describe_returns_a_string_for_empty_and_filled_params(name: str) -> None:
    spec = ACTIONS[name]
    assert isinstance(spec.describe({}), str) and spec.describe({})
    sample = _SAMPLE.get(name, {})
    assert isinstance(spec.describe(sample), str) and spec.describe(sample)


@pytest.mark.parametrize("name", sorted(ACTIONS))
def test_render_card_returns_lines_for_empty_and_filled_params(name: str) -> None:
    spec = ACTIONS[name]
    if spec.render_card is None:
        pytest.skip(f"{name} has no render_card")
    assert isinstance(spec.render_card({}, {}), list)
    sample = _SAMPLE.get(name, {})
    lines = spec.render_card(sample, {})
    assert isinstance(lines, list)
    assert all(isinstance(line, str) for line in lines)


def test_render_assign_resolves_member_name_from_resolved_map() -> None:
    """The assign card prefers the app-supplied id->name map over the raw id."""
    spec = ACTIONS["assign_work_item"]
    assert spec.render_card is not None
    resolved = {"member_names": {"MEM#1": "Sam"}}
    assert spec.render_card({"member_id": "MEM#1"}, resolved) == ["Assign to: Sam"]
    # Unknown id falls back to an id token.
    assert spec.render_card({"member_id": "MEM#9"}, {}) == ["Assign to: member MEM#9"]


def test_render_reschedule_uses_target_label() -> None:
    spec = ACTIONS["reschedule_timed_event"]
    assert spec.render_card is not None
    lines = spec.render_card(
        {"local_start_at": "2026-02-02T09:00"}, {"target_label": "Dentist"}
    )
    assert lines == ["Event: Dentist", "New time: 2026-02-02T09:00"]
