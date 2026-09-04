"""Prompt templates for the two-LLM-call capture pipeline (LLD OQ-1).

Backend-agnostic (any LLM backend uses the same role/rules; nothing Ollama-
specific here), so this lives in the plugin next to ``world.py`` / ``tools.py``
rather than in an ``ollama`` package. Each prompt is a ``str.format`` template
plus a small filler function; the model client injects the runtime pieces
(now/tz, the views, the note) at call time and applies its own ``format`` JSON
schema on top.

Two calls (see spec/LLD-assistant-pipeline.md):

  CALL 1 — LINK:    shallow WorldView + note  -> which entity ids the note is about
  CALL 2 — PROPOSE: tools view + deep context + note -> [ProposedAction] (id-free)

These are **v1 drafts** — expect to tune wording against real model output on the
host. The JSON shapes here are the contract the client's schema also enforces.
"""

from __future__ import annotations

from datetime import datetime

# --- CALL 1: LINK (entity resolution) -------------------------------------
# Input: the shallow world (id-bearing menu) + the raw note.
# Output: which existing entities the note refers to (ids only). This call does
# NOT propose actions — it only points at the relevant work items / events so a
# deterministic deep-fetch can pull their full records for the propose call.

LINK_SYSTEM = """\
You link a short household note to the existing items and events it refers to.

You are given THE WORLD (the family's members, open work items, and recent/
upcoming events, each with an id like [w3] or [e8]) and THE NOTE (free text a
family member just typed). Decide which existing work items and events — if any —
the note is about.

Rules:
- Reference ONLY ids that appear in THE WORLD. Never invent an id.
- A note may refer to nothing existing (a brand-new task/event): return empty
  lists. It may refer to more than one.
- Match on meaning, not just words ("the sink guy" -> a plumber item; "friday's
  game" -> an event on that date). Resolve relative dates in the family timezone
  ({timezone}); right now it is {now}.
- Do NOT decide what to do about them — only identify them.

Return JSON exactly:
{{"work_item_ids": [<int>, ...], "event_ids": [<int>, ...]}}
"""

LINK_CONTEXT = """\
THE WORLD:
{world_view}

THE NOTE:
"{note}"
"""


def build_link_prompt(*, world_view: str, note: str, now: datetime, timezone: str):
    """Return (system, user) for the LINK call.

    ``world_view`` is ``build_world_view(...)`` output; ``note`` is the raw
    capture text. The client sends these as the system + user messages and
    constrains output to the ``{work_item_ids, event_ids}`` schema.
    """
    system = LINK_SYSTEM.format(timezone=timezone, now=now.isoformat())
    user = LINK_CONTEXT.format(world_view=world_view, note=note)
    return system, user


# --- CALL 2: PROPOSE (action planning) ------------------------------------
# Input: the tools view (menu) + the DEEP, NARROW context (full records —
# incl. the target work item's whole update history — for only the linked ids)
# + the note. Output: zero or more tool calls, WITHOUT ids (the server attaches
# the target from what LINK resolved).

PROPOSE_SYSTEM = """\
You are a household assistant. A family member typed a short note. Propose the
actions from AVAILABLE TOOLS that carry out what they mean — nothing more.

You are also given CONTEXT: the specific item(s)/event(s) the note is about,
including a work item's recent update history, so you can reason about what has
already happened.

Rules:
- Propose ONLY tools from AVAILABLE TOOLS, using their exact names and parameter
  names. If a tool lists "(exactly one of: ...)", supply exactly one such group.
- Do NOT include any entity id in params — the item/event being acted on is
  already known from CONTEXT and is attached for you. Only supply the payload
  params a tool lists.
- Resolve relative dates/times in the family timezone ({timezone}) and emit
  datetimes as UTC ISO-8601 (e.g. 2026-09-04T19:00:00Z). Right now it is {now}.
- If nothing sensible applies, return exactly one no_action.
- Prefer one precise action over several speculative ones.

Return JSON exactly:
{{"actions": [{{"name": "<tool>", "params": {{ ... }}}}, ...]}}
"""

PROPOSE_CONTEXT = """\
{tools_view}

CONTEXT:
{deep_context}

THE NOTE:
"{note}"
"""


def build_propose_prompt(
    *, tools_view: str, deep_context: str, note: str, now: datetime, timezone: str
):
    """Return (system, user) for the PROPOSE call.

    ``tools_view`` is ``build_tools_view(registry)``; ``deep_context`` is a
    rendering of the deep-fetched records for the linked ids (target item + its
    update history, linked events); ``note`` is the raw capture text.
    """
    system = PROPOSE_SYSTEM.format(timezone=timezone, now=now.isoformat())
    user = PROPOSE_CONTEXT.format(
        tools_view=tools_view, deep_context=deep_context, note=note
    )
    return system, user
