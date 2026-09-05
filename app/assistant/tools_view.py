"""``build_tools_view`` — the LLM-facing render of the action registry.

The parallel of ``build_world_view``: where the world view is "state of the
world", the tools view is "the tools you can call" — the menu of actions the
model may propose, rendered to plain text for the prompt from each spec's
``prompt_line``.

Vocabulary: "actions" are what we *execute* (the engine's ``ActionSpec`` /
``ActionRegistry`` / ``ProposedAction``); "tools" are how those same actions are
*presented to the LLM*. An action becomes a tool only here, at the model
boundary. This renders generic spec fields (name/description/params) and imports
nothing model-specific, so it lives in ``app/assistant/`` alongside the world view.
"""

from __future__ import annotations

from app.routing.engine import ActionRegistry

_NTAKE_TOOL_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "WORK ITEMS — create and state",
        (
            "create_work_item",
            "start_work_item",
            "move_to_on_deck",
            "move_to_todo",
            "complete_work_item",
            "reopen_work_item",
            "archive_work_item",
            "archive_all_done",
        ),
    ),
    (
        "WORK ITEMS — details",
        ("append_update", "assign_work_item", "set_due_date", "set_work_item_tags"),
    ),
    ("CHECKLISTS", ("add_checklist_items", "check_off_items")),
    (
        "EVENTS — create and timing",
        (
            "create_timed_event",
            "create_all_day_event",
            "reschedule_timed_event",
            "reschedule_all_day_event",
        ),
    ),
    (
        "EVENTS — details",
        (
            "set_event_location",
            "add_event_participants",
            "set_event_tags",
            "delete_event",
            "deconflict_events",
        ),
    ),
    ("NO ACTION", ("no_action",)),
)


def build_tools_view(registry: ActionRegistry) -> str:
    """Render an arbitrary registry as one flat LLM tool menu."""
    lines = ["AVAILABLE TOOLS:"]
    lines += [spec.prompt_line for spec in registry.all()]
    return "\n".join(lines)


def build_ntake_tools_view(registry: ActionRegistry) -> str:
    """Render the ntake registry in intent-oriented model-facing sections."""
    lines = ["AVAILABLE TOOLS:"]
    for heading, names in _NTAKE_TOOL_SECTIONS:
        specs = [registry.get(name) for name in names]
        present = [spec for spec in specs if spec is not None]
        if not present:
            continue
        lines.extend(["", heading])
        lines.extend(spec.prompt_line for spec in present)
    return "\n".join(lines)
