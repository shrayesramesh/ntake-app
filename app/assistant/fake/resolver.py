"""``FakeCaptureResolver`` — the deterministic v1 stage-1 resolver (no LLM).

Stage-1 sibling of ``FakeAssistant``: it builds the ``FocusedContext`` the
assistant reasons over, running the real two-call *shape* with a deterministic,
model-free LINK — ``fake_link`` (resolve target ids from the note) →
``deep_context`` (render the full records for those ids). It is the app-coupled
capture stage (it touches the DB); the ``FocusedContext`` it returns is the
session-free value object that crosses into stage 2.

(The real ``OllamaCaptureResolver`` — task 7 — will additionally call
``build_world_view`` to feed its LINK *prompt*; the fake link matches against the
DB directly and needs no rendered world view, so it is not built here.)

Selected via ``NTAKE_ASSISTANT`` through
``app.assistant.factory.get_capture_resolver``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.assistant.base import CaptureRequest, CaptureResolver, FocusedContext
from app.assistant.fake.link import fake_link
from app.assistant.resolve import deep_context
from app.models import Member


class FakeCaptureResolver(CaptureResolver):
    """Deterministic v1 resolver (no LLM).

    Resolves target ids from the note deterministically (``fake_link``) and
    renders the deep context for them (the real ``deep_context``, which also
    always unions in the capturing member's own footprint). No model anywhere.
    """

    def focus(
        self, request: CaptureRequest, session: Session, member: Member
    ) -> FocusedContext:
        wi_ids, ev_ids = fake_link(
            session, member.family_id, request.text, request.now, request.timezone
        )
        dc = deep_context(session, member, wi_ids, ev_ids)
        return FocusedContext(
            text=request.text,
            timezone=request.timezone,
            now=request.now,
            deep_context=dc,
            resolved_work_item_ids=wi_ids,
            resolved_event_ids=ev_ids,
        )
