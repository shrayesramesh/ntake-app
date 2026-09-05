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


def test_ntake_tools_view_groups_the_real_registry_by_intent():
    from app.assistant.tools_view import build_ntake_tools_view

    out = build_ntake_tools_view(REGISTRY)

    assert out.startswith("AVAILABLE TOOLS:")
    assert "WORK ITEMS — create and state" in out
    assert "WORK ITEMS — details" in out
    assert "CHECKLISTS" in out
    assert "EVENTS — create and timing" in out
    assert "EVENTS — details" in out
    assert "NO ACTION" in out
    assert out.index("start_work_item") < out.index("check_off_items")
    assert out.index("check_off_items") < out.index("create_timed_event")
    assert out.index("create_timed_event") < out.index("set_event_location")
    for name in REGISTRY.names():
        assert name in out


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
