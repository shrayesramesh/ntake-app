"""``LocalLlmCaptureResolver`` — the LINK call (LLM call 1).

Stage-1 seam (:class:`CaptureResolver`) backed by a real model — the app-coupled
capture stage. It renders the shallow ``build_world_view`` (the id-bearing menu of
members / open items / windowed events) + the note into the LINK prompt, asks the
injected :class:`LLM` seam which existing entities the note refers to, then runs
the shared deterministic tail — ``parse_ids`` (tolerant parse) → ``deep_context``
(whitelist the ids to the family + union the member's footprint + render) — to
build the session-free :class:`FocusedContext` that crosses into stage 2.

Mirrors ``FakeCaptureResolver`` but with a real LINK: where the fake matches the
DB directly (``fake_link``), this asks the model. The tail is identical, so the
same **validate-don't-trust** guarantee holds — ``deep_context`` drops any id the
model returned that isn't in the capturing member's family.

Depends on the ``LLM`` protocol, never on httpx. A malformed/degenerate LINK
reply parses to no ids (graceful-degrade) rather than raising.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.assistant.base import CaptureRequest, CaptureResolver, FocusedContext
from app.assistant.deep_context import deep_context, parse_ids, resolve_ids
from app.assistant.local_llm.protocol import LLM
from app.assistant.prompts import build_link_prompt
from app.assistant.world_view import build_world_view
from app.models import Member

# The LINK call's constrained-output schema: a fixed two-id-list shape (NOT
# derived from the action registry — linking names entities, it doesn't propose
# actions). The one place the LINK JSON contract is expressed to the model.
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
