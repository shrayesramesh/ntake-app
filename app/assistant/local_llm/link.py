"""LINK stage: build the broad context prompt, constrain ids, and focus a capture."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.assistant.base import CaptureRequest, CaptureResolver, FocusedContext
from app.assistant.context.deep import deep_context, resolve_ids
from app.assistant.context.linking import add_capturing_member_for_first_person
from app.assistant.context.world import build_world_view
from app.assistant.local_llm.protocol import LLM
from app.persistence.models import Member

# --- CALL 1: LINK (entity resolution) -------------------------------------
# Input: the shallow world (id-bearing menu) + the raw note.
# Output: which existing entities the note refers to (ids only). This call does
# NOT propose actions — it only points at the relevant work items / events so a
# deterministic deep-fetch can pull their full records for the propose call.

LINK_SYSTEM = """\
You link a short household note to the existing items, events, and people it
refers to.

You are given THE WORLD (the family's members, open work items, and recent/
upcoming events, each with an id like [m2], [w3] or [e8]) and THE NOTE (free text
a family member just typed). Decide which existing work items, events, and family
members — if any — the note is about.

Rules:
- Reference ONLY ids that appear in THE WORLD. Never invent an id or infer the
  next numeric id.
- A note may refer to nothing existing (a brand-new task/event): return empty
  lists. It may refer to more than one. If uncertain whether an existing entity
  is intended, prefer an empty list to a guessed link.
- Include a member id in member_ids when the note is ABOUT that person (e.g.
  "Alex's day off" -> that member; "drive Sam to practice" -> Sam), so their
  existing workload/events can inform what to do. Match people by name.
- Match on meaning, not just words ("the sink guy" -> a plumber item; "friday's
  game" -> an event on that date). Resolve relative dates in the family timezone
  ({timezone}); right now it is {now}.
- Do NOT decide what to do about them — only identify them.

Return JSON exactly:
{{"work_item_ids": [<int>, ...], "event_ids": [<int>, ...], "member_ids": [<int>, ...]}}
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


_LINK_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["work_item_ids", "event_ids", "member_ids"],
    "properties": {
        "work_item_ids": {"type": "array", "items": {"type": "integer"}},
        "event_ids": {"type": "array", "items": {"type": "integer"}},
        "member_ids": {"type": "array", "items": {"type": "integer"}},
    },
}


def parse_ids(link_json: dict) -> tuple[list[int], list[int], list[int]]:
    """Parse the LINK call's JSON into (work_item_ids, event_ids, member_ids).

    Tolerant of untrusted model output: missing keys → empty; non-list values →
    empty. Each entry is coerced to the entity's **integer** id (see
    ``_coerce_ids``): an int, a numeric string, or the matching-prefix token
    (``w`` for work items, ``e`` for events, ``m`` for members,
    case-insensitive); anything else is dropped.
    """
    return (
        _coerce_ids(link_json.get("work_item_ids"), "w"),
        _coerce_ids(link_json.get("event_ids"), "e"),
        _coerce_ids(link_json.get("member_ids"), "m"),
    )


def _coerce_ids(value: object, prefix: str) -> list[int]:
    """Coerce a list of untrusted id tokens to ints for one entity kind.

    Accepts: a bare ``int`` (not ``bool``); a numeric string (``"5"``); or the
    kind's token ``<prefix><digits>`` (``"e8"``, case-insensitive). Drops
    everything else (wrong prefix, non-numeric, floats, None).
    """
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for x in value:
        coerced = _coerce_one(x, prefix)
        if coerced is not None:
            out.append(coerced)
    return out


def _coerce_one(x: object, prefix: str) -> int | None:
    if isinstance(x, bool):  # bool subclasses int — never an id
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        token = x.strip()
        # Strip one leading matching-prefix letter (w3/e8), case-insensitive.
        if token[:1].lower() == prefix:
            token = token[1:]
        return int(token) if token.isdigit() else None
    return None


class LocalLlmCaptureResolver(CaptureResolver):
    """Resolve a capture to a focused context via one LINK LLM call + deep fetch."""

    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def focus(
        self, request: CaptureRequest, session: Session, member: Member
    ) -> FocusedContext:
        world = build_world_view(
            session, member.family_id, request.now, request.timezone
        )
        system, user = build_link_prompt(
            world_view=world,
            note=request.text,
            now=request.now,
            timezone=request.timezone,
        )
        link_json = self._llm.complete(system=system, user=user, schema=_LINK_SCHEMA)
        raw_wi_ids, raw_ev_ids, raw_mem_ids = parse_ids(link_json)
        raw_mem_ids = add_capturing_member_for_first_person(
            request.text, raw_mem_ids, member.id
        )
        # Validate-don't-trust: whitelist the model's ids to the member's family
        # BEFORE they reach the context (they become attachable targets), so a
        # hallucinated/foreign id is dropped everywhere — not just in rendering.
        wi_ids, ev_ids, mem_ids = resolve_ids(
            session, member, raw_wi_ids, raw_ev_ids, raw_mem_ids
        )
        dc = deep_context(session, member, wi_ids, ev_ids, mem_ids)
        return FocusedContext(
            text=request.text,
            timezone=request.timezone,
            now=request.now,
            deep_context=dc,
            resolved_work_item_ids=wi_ids,
            resolved_event_ids=ev_ids,
            resolved_member_ids=mem_ids,
        )
