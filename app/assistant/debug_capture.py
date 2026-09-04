"""Debug scaffolding for live-LLM UI testing — NOT committed behavior.

This module exists to make the capture pipeline observable in the browser while
debugging the live local LLM: it records the exact prompts sent to the model, the
raw JSON the model returned, and the intermediate pipeline artifacts (the world
view, the LINK result, the deep context). None of this changes the pipeline's
behavior — it wraps the real ``LLM`` seam and re-runs the same two stages the
endpoint would, capturing everything as it flows.

Kept as a standalone module (rather than edits scattered through the committed
seams) so it is trivial to delete when the debugging session ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.assistant.capture import CaptureRequest, FocusedContext, ProposedAction
from app.assistant.local_llm.assistant import LocalLlmAssistant
from app.assistant.local_llm.protocol import LLM, Json
from app.assistant.local_llm.resolver import LocalLlmCaptureResolver
from app.models import Member


@dataclass
class LlmCall:
    """One recorded ``complete()`` round trip through the model seam."""

    system: str
    user: str
    schema: Json
    reply: Json


class RecordingLLM:
    """An :class:`LLM` that delegates to a real client and records every call.

    Structural typing: it satisfies the ``LLM`` protocol (a single ``complete``)
    without inheriting anything, so it can stand in anywhere the resolver/assistant
    expect an ``LLM``. Each round trip is appended to :attr:`calls` in order —
    call 1 is LINK, call 2 is PROPOSE.
    """

    def __init__(self, inner: LLM) -> None:
        self._inner = inner
        self.calls: list[LlmCall] = []

    def complete(self, system: str, user: str, schema: Json) -> Json:
        reply = self._inner.complete(system=system, user=user, schema=schema)
        self.calls.append(LlmCall(system=system, user=user, schema=schema, reply=reply))
        return reply


@dataclass
class CaptureDebug:
    """The observable trace of one live capture, for the UI debug panel."""

    link_system: str = ""
    link_user: str = ""
    link_reply: Json = field(default_factory=dict)
    resolved_work_item_ids: list[int] = field(default_factory=list)
    resolved_event_ids: list[int] = field(default_factory=list)
    resolved_member_ids: list[int] = field(default_factory=list)
    deep_context: str = ""
    propose_system: str = ""
    propose_user: str = ""
    propose_reply: Json = field(default_factory=dict)


def run_capture_with_debug(
    inner: LLM,
    request: CaptureRequest,
    session: Session,
    member: Member,
) -> tuple[FocusedContext, list[ProposedAction], CaptureDebug]:
    """Run the real two-stage local pipeline, recording prompts + raw replies.

    Uses the SAME resolver + assistant the endpoint uses, but with a recording
    wrapper around the shared model seam so both stages' prompts and replies are
    captured. Returns the focused context, the proposed actions, and the debug
    trace. Behavior is identical to the normal path — this only observes.
    """
    recorder = RecordingLLM(inner)
    resolver = LocalLlmCaptureResolver(recorder)
    assistant = LocalLlmAssistant(recorder)

    ctx = resolver.focus(request, session, member)
    actions = assistant.propose(ctx)

    debug = CaptureDebug(
        resolved_work_item_ids=list(ctx.resolved_work_item_ids),
        resolved_event_ids=list(ctx.resolved_event_ids),
        resolved_member_ids=list(ctx.resolved_member_ids),
        deep_context=ctx.deep_context,
    )
    # calls[0] = LINK, calls[1] = PROPOSE (in pipeline order).
    if len(recorder.calls) >= 1:
        c = recorder.calls[0]
        debug.link_system, debug.link_user, debug.link_reply = c.system, c.user, c.reply
    if len(recorder.calls) >= 2:
        c = recorder.calls[1]
        debug.propose_system, debug.propose_user, debug.propose_reply = (
            c.system,
            c.user,
            c.reply,
        )
    return ctx, actions, debug
