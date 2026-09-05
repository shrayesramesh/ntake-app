"""Registry-wide contracts for the assistant action plugin."""

from __future__ import annotations

from app.assistant.actions.events import EVENT_ACTIONS
from app.assistant.actions.meta import META_ACTIONS
from app.assistant.actions.registry import ACTIONS, REGISTRY
from app.assistant.actions.work_items import WORK_ITEM_ACTIONS


def test_registry_has_v1_actions():
    assert set(ACTIONS) == {
        "set_due_date",
        "create_timed_event",
        "create_all_day_event",
        "complete_work_item",
        "start_work_item",
        "move_to_on_deck",
        "move_to_todo",
        "reopen_work_item",
        "assign_work_item",
        "archive_work_item",
        "archive_all_done",
        "add_checklist_items",
        "check_off_items",
        "create_work_item",
        "append_update",
        "reschedule_timed_event",
        "reschedule_all_day_event",
        "no_action",
        "deconflict_events",
        "delete_event",
        "set_event_location",
        "add_event_participants",
    }


def test_registry_orders_work_item_event_and_meta_domains():

    assert list(ACTIONS) == [
        *WORK_ITEM_ACTIONS,
        *EVENT_ACTIONS,
        *META_ACTIONS,
    ]


def test_every_action_has_a_describe():
    # describe(params) -> the deterministic, registry-derived action_summary
    # (ground truth: what the action WILL do), separate from any LLM narration.
    for name, spec in ACTIONS.items():
        assert callable(spec.describe), name


def test_all_actions_are_wellformed():
    """Registry-wide contract guard: every action (including any added later) is
    well-formed, so a new entry can't silently break the propose/confirm flow.

    Each spec must have a callable apply + describe, a describe that returns a
    non-empty str on empty params (it runs on unconfirmed proposals), and
    boolean needs_target/logs flags. no_action is the sole logs=False entry.
    """
    for name, spec in ACTIONS.items():
        assert callable(spec.apply), f"{name}: apply not callable"
        assert callable(spec.describe), f"{name}: describe not callable"
        assert isinstance(spec.describe({}), str) and spec.describe({}), name
        assert isinstance(spec.needs_target, bool), name
        assert isinstance(spec.logs, bool), name
        assert isinstance(spec.required, list), name
    # Exactly the actions that don't operate on an existing item skip a target.
    assert ACTIONS["create_work_item"].needs_target is False
    assert ACTIONS["archive_all_done"].needs_target is False
    assert ACTIONS["no_action"].needs_target is False
    # Non-logging actions: no_action (meta) and event-only actions (no work item
    # to log against, e.g. deconflict_events / reschedule_timed_event).
    assert {n for n, s in ACTIONS.items() if not s.logs} == {
        "no_action",
        "deconflict_events",
        "reschedule_timed_event",
        "reschedule_all_day_event",
        "delete_event",
        "set_event_location",
        "add_event_participants",
        "archive_all_done",
    }


def test_describe_set_due_date_uses_param():
    text = ACTIONS["set_due_date"].describe({"due_at": "2026-09-05T19:00:00+00:00"})
    assert "2026-09-05" in text
    assert "due" in text.lower()


def test_describe_create_timed_event_uses_title():
    text = ACTIONS["create_timed_event"].describe(
        {"title": "Plumber visit", "start_at": "2026-09-05T19:00:00+00:00"}
    )
    assert "Plumber visit" in text
    assert "event" in text.lower()


def test_describe_complete_work_item():
    text = ACTIONS["complete_work_item"].describe({})
    assert "done" in text.lower() or "complete" in text.lower()


def test_describe_create_work_item_uses_title():
    text = ACTIONS["create_work_item"].describe({"title": "buy stamps"})
    assert "buy stamps" in text


def test_describe_no_action():
    text = ACTIONS["no_action"].describe({})
    assert isinstance(text, str) and text


def test_describe_is_deterministic():
    params = {"due_at": "2026-09-05T19:00:00+00:00"}
    a = ACTIONS["set_due_date"].describe(params)
    b = ACTIONS["set_due_date"].describe(params)
    assert a == b


def test_describe_create_timed_event_title_only():
    # Title but no timing yet: still a meaningful, deterministic summary with no
    # dangling "at <when>" clause.
    text = ACTIONS["create_timed_event"].describe({"title": "Plumber visit"})
    assert "Plumber visit" in text
    assert " at " not in text


def test_describe_action_seam_resolves_and_falls_back():

    # Known action -> the registry-derived summary.
    got = REGISTRY.describe("create_work_item", {"title": "buy stamps"})
    assert "buy stamps" in got
    # Unknown action -> the name itself (display-only; never raises).
    assert REGISTRY.describe("frobnicate", {}) == "frobnicate"


def test_describe_tolerates_missing_params():
    # describe runs on unconfirmed proposals; it must not raise on absent keys
    # (validation happens at apply time, not describe time).
    for spec in ACTIONS.values():
        assert isinstance(spec.describe({}), str)


def test_card_renderers_tolerate_unconfirmed_partial_params():
    """Proposal-card detail rendering must be safe before confirmation.

    The model may return partial parameters that are later rejected at confirm
    time; renderers still need to describe the proposal without raising.
    """
    for name, spec in ACTIONS.items():
        if spec.render_card is not None:
            assert isinstance(spec.render_card({}, {}), list), name
