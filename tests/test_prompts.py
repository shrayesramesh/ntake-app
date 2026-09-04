"""Prompt template builders for the two capture LLM calls (link, propose).

Drafts — wording will be tuned against real model output — so these tests assert
structure/substitution, not exact prose: placeholders are filled (no stray
``{...}``), the injected views/note/temporal frame appear, and the JSON-shape
contract is stated.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.assistant.prompts import build_link_prompt, build_propose_prompt

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _no_unfilled_placeholders(s: str) -> bool:
    # no leftover single-brace template fields like {world_view}; JSON braces in
    # the templates are escaped ({{ }}) so they render as literal { }.
    return not re.search(r"\{[a-z_]+\}", s)


# --- LINK -----------------------------------------------------------------


def test_link_prompt_fills_and_embeds_inputs():
    system, user = build_link_prompt(
        world_view="FAMILY MEMBERS:\n- [m1] Priya (adult)",
        note="the sink guy is coming friday",
        now=NOW,
        timezone=TZ,
    )
    assert _no_unfilled_placeholders(system)
    assert _no_unfilled_placeholders(user)
    # temporal frame injected into the system prompt
    assert TZ in system and NOW.isoformat() in system
    # the world + note are in the user message
    assert "[m1] Priya" in user
    assert "the sink guy is coming friday" in user
    # link output contract stated, and it must NOT propose actions
    assert "work_item_ids" in system and "event_ids" in system
    assert "actions" not in system.lower()


def test_link_prompt_forbids_inventing_ids():
    system, _ = build_link_prompt(world_view="x", note="y", now=NOW, timezone=TZ)
    assert "invent" in system.lower()  # the "never invent an id" rule is present


# --- PROPOSE --------------------------------------------------------------


def test_propose_prompt_fills_and_embeds_inputs():
    system, user = build_propose_prompt(
        tools_view="AVAILABLE TOOLS:\n- set_due_date: ... — params: due_at: datetime",
        deep_context="[w1] call plumber (doing)\n  - update: left a voicemail",
        note="he's coming friday at 3",
        now=NOW,
        timezone=TZ,
    )
    assert _no_unfilled_placeholders(system)
    assert _no_unfilled_placeholders(user)
    assert TZ in system and NOW.isoformat() in system
    assert "set_due_date" in user  # tools view embedded
    assert "left a voicemail" in user  # deep context (update history) embedded
    assert "he's coming friday at 3" in user
    # propose output contract + the id-free / no_action rules
    assert '"actions"' in system
    assert "no_action" in system
    assert "id" in system.lower()  # the "do NOT include any entity id" rule


def test_propose_prompt_states_utc_and_one_of_rules():
    system, _ = build_propose_prompt(
        tools_view="x", deep_context="y", note="z", now=NOW, timezone=TZ
    )
    assert "UTC" in system
    assert "exactly one" in system.lower()  # the exclusive-params guidance
