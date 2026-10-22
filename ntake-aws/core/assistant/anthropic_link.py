"""LINK stage — ground a capture to existing entities via one Anthropic call.

The stage-1 :class:`CaptureResolver` (AWS_LLD §3.1): build the world view, ask
the model which existing work items / events / members the note refers to via a
**forced ``record_links`` tool** (constrained JSON — the forced-tool shape chosen
from ``scripts/spike/link_probe.py``), then run the model's answer through the
deterministic grounding steps — first-person linking, validate-against-family
(``resolve_ids`` — drops foreign ids, de-dups), and ``deep_context`` — to produce
the ``FocusedContext`` stage 2 proposes over.

Graceful-degrade: the model call is untrusted. Any failure (API error, missing
``tool_use`` block, non-conforming ``input``) degrades the model's contribution
to **no linked ids** — it never raises into the request path. The deterministic
steps (first-person linking, deep-context over whatever ids survived) still run,
so a degraded LINK yields an empty-but-valid context rather than a crash.

LINK **never emits actions** — it only grounds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.assistant.anthropic_client import AnthropicClient
from core.assistant.base import CaptureRequest, CaptureResolver, FocusedContext
from core.assistant.deep import deep_context, resolve_ids
from core.assistant.linking import add_capturing_member_for_first_person
from core.assistant.world import build_world_view
from core.repository import Repository
from core.schemas import Member

_LINK_TOOL_NAME = "record_links"

# The forced tool whose `input` IS the {ids} object (AWS_LLD §3.1 / probe).
_LINK_TOOL: dict[str, Any] = {
    "name": _LINK_TOOL_NAME,
    "description": "Record which existing entities the note refers to.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["work_item_ids", "event_ids", "member_ids"],
        "properties": {
            "work_item_ids": {"type": "array", "items": {"type": "string"}},
            "event_ids": {"type": "array", "items": {"type": "string"}},
            "member_ids": {"type": "array", "items": {"type": "string"}},
        },
    },
}

_SYSTEM = """\
Identify which existing entities a household note refers to — nothing more.

THE WORLD lists the family's members, open work items, and recent/upcoming
events, each tagged [m:<id>], [w:<id>], or [e:<id>]. Call record_links with the
ids the note is about (bare ids, no brackets or prefix); empty lists if none.

Rules:
- Use ONLY ids from THE WORLD; never invent one.
- An item/event needs distinguishing evidence (title, person, date, location, or
  a clear alias) — a shared topic alone is not enough.
- Decide members independently; include a person the note names even for a new
  task/event. Match on meaning. Resolve relative dates in {timezone} (now: {local_now}).
- Do NOT decide what to do — only identify."""

_USER = """\
THE WORLD:
{world_view}

THE NOTE:
"{note}\""""


def build_link_prompt(
    *, world_view: str, note: str, now: datetime, timezone: str
) -> tuple[str, str]:
    """Return (system, user) for the LINK call (family-local ``now`` in the prompt)."""
    aware = now if now.tzinfo else now.replace(tzinfo=UTC)
    local_now = aware.astimezone(ZoneInfo(timezone)).replace(tzinfo=None).isoformat()
    system = _SYSTEM.format(timezone=timezone, local_now=local_now)
    user = _USER.format(world_view=world_view, note=note)
    return system, user


def parse_link_ids(response: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """Pull (work_item_ids, event_ids, member_ids) from the forced-tool response.

    Tolerant of untrusted output: a missing ``tool_use`` block, a wrong tool name,
    a non-dict ``input``, or non-list / non-string entries all degrade to empty —
    never raise. Only well-formed string ids survive (validated against the family
    downstream).
    """
    for block in response.get("content", []):
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") != _LINK_TOOL_NAME:
            continue
        data = block.get("input")
        if not isinstance(data, dict):
            return [], [], []
        return (
            _str_ids(data.get("work_item_ids")),
            _str_ids(data.get("event_ids")),
            _str_ids(data.get("member_ids")),
        )
    return [], [], []


def _str_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, str) and x]


class AnthropicCaptureResolver(CaptureResolver):
    """Resolve a capture to a focused context: one LINK call + grounding."""

    def __init__(self, client: AnthropicClient) -> None:
        self._client = client

    def focus(
        self, request: CaptureRequest, repo: Repository, member: Member
    ) -> FocusedContext:
        raw_wi, raw_ev, raw_mem = self._link(request, repo, member)

        # Deterministic first-person linking, then validate-against-family.
        raw_mem = add_capturing_member_for_first_person(
            request.text, raw_mem, member.id
        )
        wi_ids, ev_ids, mem_ids = resolve_ids(repo, member, raw_wi, raw_ev, raw_mem)
        dc = deep_context(repo, member, wi_ids, ev_ids, mem_ids)

        return FocusedContext(
            text=request.text,
            timezone=request.timezone,
            now=request.now,
            capture_author=f"[m:{member.id}] {member.display_name} ({member.role})",
            deep_context=dc,
            resolved_work_item_ids=wi_ids,
            resolved_event_ids=ev_ids,
            resolved_member_ids=mem_ids,
        )

    def _link(
        self, request: CaptureRequest, repo: Repository, member: Member
    ) -> tuple[list[str], list[str], list[str]]:
        """The untrusted model call — degrades to empty ids on ANY failure."""
        try:
            world = build_world_view(
                repo, member.family_id, request.now, request.timezone
            )
            system, user = build_link_prompt(
                world_view=world,
                note=request.text,
                now=request.now,
                timezone=request.timezone,
            )
            response = self._client.create_message(
                system,
                [{"role": "user", "content": [{"type": "text", "text": user}]}],
                tools=[_LINK_TOOL],
                tool_choice={"type": "tool", "name": _LINK_TOOL_NAME},
            )
            return parse_link_ids(response)
        except Exception:  # noqa: BLE001 — never raise into the request path
            return [], [], []
