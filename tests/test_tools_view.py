"""build_tools_view — the LLM-facing render of the action registry (ToolsView).

Parallel to test_world_view: pin the ENTIRE rendered tools menu over the real
ntake REGISTRY, so the exact tool list the model will see is visible and
reviewable here (and any drift — a new action, a changed param, a renamed
description — is caught). Plus a few structural tests over a tiny hand-built
registry.
"""

from __future__ import annotations

from app.assistant.actions import REGISTRY
from app.assistant.tools import build_tools_view
from app.routing import ActionRegistry, ActionSpec, Param


def test_tools_view_full_render_over_the_real_registry():
    # The exact prompt text the model sees. If this changes, it's a deliberate
    # change to the tool contract — update the snapshot on purpose.
    expected = (
        "AVAILABLE TOOLS:\n"
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
        "- create_event: Create a calendar event (timed OR all-day). — params: "
        "title: string, description: string?, location: string?, start_at: datetime?, "
        "end_at: datetime?, start_date: date?, end_date: date?  "
        "(exactly one of: {start_at, end_at} OR {start_date, end_date})\n"
        "- reschedule_event: Move an existing event to new timing (timed OR "
        "all-day). — params: start_at: datetime?, end_at: datetime?, "
        "start_date: date?, end_date: date?  "
        "(exactly one of: {start_at, end_at} OR {start_date, end_date})\n"
        "- create_work_item: Create a new work item (a task/todo). — params: "
        "title: string, description: string?, tags: array<string>?\n"
        "- no_action: Nothing to suggest. — params: (no params)\n"
        "- deconflict_events: Move an event to the next day to resolve a "
        "same-time conflict. — params: (no params)"
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
                params=[Param("x", "string", required=True)],
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
