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


def test_propose_prompt_states_a_local_clock_and_explicit_time_check():
    system, _ = build_propose_prompt(
        tools_view="x", deep_context="y", note="z", now=NOW, timezone=TZ
    )

    assert "2026-09-03T08:00:00-04:00" in system
    assert "weekday" in system.lower()
    assert "back to the family timezone" in system.lower()
    assert "verify it" in system.lower()


# --- integration: the REAL assembled prompts over populated_family --------
# Full-text golden-file snapshots of both calls, assembled from build_world_view
# / build_tools_view / deep_context. The .txt files under tests/expectations/ are
# the reviewable artifacts — open them to see exactly what the model receives.
# Regenerate after an intentional prompt change: NTAKE_UPDATE_EXPECTATIONS=1.


def test_assembled_link_prompt_over_populated_family(session, populated_family):
    from app.assistant.world_view import build_world_view
    from tests.expectations import assert_matches_expectation

    p = populated_family
    world = build_world_view(session, p.family.id, p.now, p.tz)
    system, user = build_link_prompt(
        world_view=world, note="he's coming friday at 3", now=p.now, timezone=p.tz
    )
    assert_matches_expectation("link_prompt_system", system)
    assert_matches_expectation("link_prompt_user", user)


def test_assembled_propose_prompt_over_populated_family(session, populated_family):
    from app.assistant.actions import REGISTRY
    from app.assistant.deep_context import deep_context
    from app.assistant.tools_view import build_tools_view
    from app.models import Member
    from tests.expectations import assert_matches_expectation

    p = populated_family
    alex = session.get(Member, p.members["Alex"])
    dc = deep_context(session, alex, [p.items["doing"]], [])  # LINK resolved plumber
    system, user = build_propose_prompt(
        tools_view=build_tools_view(REGISTRY),
        deep_context=dc,
        note="he's coming friday at 3",
        now=p.now,
        timezone=p.tz,
    )
    assert_matches_expectation("propose_prompt_system", system)
    assert_matches_expectation("propose_prompt_user", user)
