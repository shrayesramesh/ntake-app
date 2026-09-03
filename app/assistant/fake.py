"""FakeAssistant — deterministic canned proposals (Phase 4, task 3).

Derives proposals from keywords in the input text so the entire
capture->propose->confirm flow is testable with no model. Deliberately simple and
predictable; it is NOT trying to be smart — the real interpretation is the
OllamaAssistant's job (task 7). Obeys the interface: read-only, returns a list of
ProposedAction with valid registry names.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.assistant.base import AssistantClient, CaptureContext, ProposedAction

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_DONE_WORDS = ("done", "finished", "completed", "complete")
_EVENT_WORDS = ("appointment", "event", "meeting", "visit")


def _next_weekday(ctx: CaptureContext, weekday: int, hour: int = 9) -> str:
    """The next occurrence of ``weekday`` at ``hour`` in the family tz, as UTC ISO."""
    tz = ZoneInfo(ctx.timezone)
    local_now = ctx.now.astimezone(tz)
    days = (weekday - local_now.weekday()) % 7
    days = days or 7  # "friday" said on a Friday means next Friday
    target = (local_now + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return target.astimezone(ZoneInfo("UTC")).isoformat()


class FakeAssistant(AssistantClient):
    def propose(self, ctx: CaptureContext) -> list[ProposedAction]:
        text = ctx.text.lower()
        proposals: list[ProposedAction] = []
        tid = ctx.work_item_id

        # New-item capture (no target): the confirmable "make this a work item"
        # path. Bare text no longer auto-creates an item — it's a proposal now.
        if tid is None:
            proposals.append(
                ProposedAction(
                    name="create_work_item",
                    params={"title": ctx.text},
                    llm_rationale="New capture — could be a work item.",
                    target_id=None,
                )
            )

        # A weekday mention → propose a due date (and an event if event-ish).
        weekday = next((wd for name, wd in _WEEKDAYS.items() if name in text), None)
        if weekday is not None:
            due = _next_weekday(ctx, weekday, hour=15)
            proposals.append(
                ProposedAction(
                    name="set_due_date",
                    params={"due_at": due},
                    llm_rationale="Detected a weekday in the text.",
                    target_id=tid,
                )
            )
            if any(w in text for w in _EVENT_WORDS):
                end = _next_weekday(ctx, weekday, hour=16)
                proposals.append(
                    ProposedAction(
                        name="create_event",
                        params={"title": ctx.text, "start_at": due, "end_at": end},
                        llm_rationale="Looks like a scheduled event.",
                        target_id=tid,
                    )
                )

        if any(w in text for w in _DONE_WORDS):
            proposals.append(
                ProposedAction(
                    name="complete_work_item",
                    params={},
                    llm_rationale="Text mentions completion.",
                    target_id=tid,
                )
            )

        if not proposals:
            proposals.append(
                ProposedAction(
                    name="no_action", params={}, llm_rationale="Nothing to suggest."
                )
            )
        return proposals
