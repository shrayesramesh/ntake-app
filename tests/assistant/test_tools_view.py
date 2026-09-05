"""build_tools_view — the LLM-facing render of the action registry (ToolsView).

Parallel to test_world_view: pin the ENTIRE rendered tools menu over the real
ntake REGISTRY, so the exact tool list the model will see is visible and
reviewable here (and any drift — a new action, a changed param, a renamed
description — is caught). Plus a few structural tests over a tiny hand-built
registry.
"""

from __future__ import annotations

from app.assistant.actions.registry import REGISTRY
from app.assistant.tools_view import build_tools_view
from app.routing.engine import ActionRegistry, ActionSpec, DataType, Param


def test_tools_view_full_render_over_the_real_registry():
    # The exact prompt text the model sees. If this changes, it's a deliberate
    # change to the tool contract — update the snapshot on purpose.
    expected = (
        "AVAILABLE TOOLS:\n"
        "- create_work_item: Create a new work item (a task/todo). — params: "
        "title: string, description: string?, tags: array<string>?, "
        "checklist_items: array<string>?\n"
        "- append_update: Append assistant context to an existing work item. — params: "
        "body: string\n"
        "- set_due_date: Set a work item's due date. — params: due_at: datetime\n"
        "- complete_work_item: Mark a work item done. — params: (no params)\n"
        "- start_work_item: Start work on an item (move it to Doing). — params: "
        "(no params)\n"
        "- move_to_on_deck: Move a work item to On deck (queued up next). — params: "
        "(no params)\n"
        "- move_to_todo: Move a work item back to Todo. — params: (no params)\n"
        "- reopen_work_item: Reopen a completed item (back to Todo; clears "
        "completion). — params: (no params)\n"
        "- assign_work_item: Assign a work item to a family member. — params: "
        "member_id: integer\n"
        "- archive_work_item: Archive a work item (only a done item may be "
        "archived). — params: (no params)\n"
        "- add_checklist_items: Add checklist items (e.g. a grocery list) to a "
        "work item. — params: items: array<string>\n"
        "- create_timed_event: Create a timed calendar event. — params: "
        "title: string, start_at: datetime, end_at: datetime, description: string?, "
        "location: string?, participants: object?\n"
        "- create_all_day_event: Create an all-day calendar event. — params: "
        "title: string, start_date: date, end_date: date?, description: string?, "
        "location: string?, participants: object?\n"
        "- reschedule_timed_event: Move an existing event to a timed range. — params: "
        "start_at: datetime, end_at: datetime\n"
        "- reschedule_all_day_event: Move an existing event to all-day date(s). — "
        "params: start_date: date, end_date: date?\n"
        "- delete_event: Delete an existing event (e.g. it was cancelled). — "
        "params: (no params)\n"
        "- deconflict_events: Move an event to the next day to resolve a "
        "same-time conflict. — params: (no params)\n"
        "- no_action: Nothing to suggest. — params: (no params)"
    )
    assert build_tools_view(REGISTRY) == expected


def test_tools_view_lists_every_registered_action():
    # Structural guard: every action name appears in the view (independent of the
    # exact wording pinned above).
    out = build_tools_view(REGISTRY)
    for name in REGISTRY.names():
        assert name in out


def test_tools_view_header_and_one_line_per_action():
    reg = ActionRegistry(
        [
            ActionSpec(
                name="a",
                description="Do A.",
                params=[Param("x", DataType.STRING, required=True)],
            ),
            ActionSpec(name="b", description="Do B."),
        ]
    )
    out = build_tools_view(reg)
    assert out == (
        "AVAILABLE TOOLS:\n"
        "- a: Do A. — params: x: string\n"
        "- b: Do B. — params: (no params)"
    )


def test_tools_view_empty_registry_is_just_the_header():
    assert build_tools_view(ActionRegistry([])) == "AVAILABLE TOOLS:"
