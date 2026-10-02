"""The LLM-facing tools view (core/assistant/tools_view.py).

Renders a registry to the prompt menu from each spec's ``prompt_line``. Infra-
agnostic — imports only ``ActionRegistry`` from the engine. Covers both the flat
render and the ntake intent-sectioned render (including the "section with no
present specs is skipped" branch).
"""

from __future__ import annotations

from typing import Any

from core.assistant.tools_view import build_ntake_tools_view, build_tools_view
from core.engine.engine import ActionRegistry, ActionSpec, DataType, Param


def _reg_flat() -> ActionRegistry[Any]:
    return ActionRegistry(
        [
            ActionSpec(
                name="create_work_item",
                description="Create a work item.",
                params=[Param("title", DataType.STRING, required=True)],
            ),
            ActionSpec(name="no_action", description="Nothing to suggest."),
        ]
    )


def test_build_tools_view_is_a_flat_menu() -> None:
    out = build_tools_view(_reg_flat())
    lines = out.splitlines()
    assert lines[0] == "AVAILABLE TOOLS:"
    assert any("create_work_item: Create a work item." in ln for ln in lines)
    assert any("no_action: Nothing to suggest." in ln for ln in lines)


def test_build_ntake_tools_view_groups_present_specs_into_sections() -> None:
    # Registry has only some of the ntake action names → only sections with at
    # least one present spec render (the empty-section branch is exercised).
    reg: ActionRegistry[Any] = ActionRegistry(
        [
            ActionSpec(name="create_work_item", description="Create a work item."),
            ActionSpec(name="no_action", description="Nothing to suggest."),
        ]
    )
    out = build_ntake_tools_view(reg)
    assert out.startswith("AVAILABLE TOOLS:")
    assert "WORK ITEMS — create and state" in out
    assert "NO ACTION" in out
    # A section whose names are all absent (e.g. CHECKLISTS) must not appear.
    assert "CHECKLISTS" not in out
    assert "EVENTS — details" not in out


def test_build_ntake_tools_view_empty_registry_is_just_header() -> None:
    assert build_ntake_tools_view(ActionRegistry([])) == "AVAILABLE TOOLS:"
