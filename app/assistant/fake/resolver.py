"""``FakeCaptureResolver`` — the deterministic v1 stage-1 resolver (no LLM).

Stage-1 sibling of ``FakeAssistant``: it builds the ``FocusedContext`` the
assistant reasons over. It is the app-coupled capture stage (it touches the DB);
the ``FocusedContext`` it returns is the session-free value object that crosses
into stage 2.

Selected via ``NTAKE_ASSISTANT`` through
``app.assistant.factory.get_capture_resolver``. The LLM-backed sibling
(``OllamaCaptureResolver``) is task 7.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.assistant.base import CaptureRequest, CaptureResolver, FocusedContext
from app.assistant.resolve import deep_context
from app.models import Member


class FakeCaptureResolver(CaptureResolver):
    """Deterministic v1 resolver (no LLM).

    Resolves NO target ids from free text yet (empty resolved lists) — the
    deterministic ``fake_link`` that populates them is wired in a following step.
    It still renders the deep context, which always includes the capturing
    member's own footprint (assigned items + participated events).
    """

    def focus(
        self, request: CaptureRequest, session: Session, member: Member
    ) -> FocusedContext:
        wi_ids: list[int] = []
        ev_ids: list[int] = []
        dc = deep_context(session, member, wi_ids, ev_ids)
        return FocusedContext(
            text=request.text,
            timezone=request.timezone,
            now=request.now,
            deep_context=dc,
            resolved_work_item_ids=wi_ids,
            resolved_event_ids=ev_ids,
        )
