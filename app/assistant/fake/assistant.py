"""FakeAssistant — deterministic canned proposals (Phase 4, task 3).

Derives proposals from keywords so the entire capture->propose->confirm flow is
testable with no model. Deliberately dumb (substring keyword matching, canned
timing) but **expressive**: the trigger vocabulary below can drive every v1
action and combination, so tests/smoke can exercise each path predictably. The
real interpretation is the OllamaAssistant's job (task 7).

Every proposal FULLY DEFINES its operation (executable in isolation): a
targeting action references a real ``target_id``; a creating action fully
specifies the new entity. A new-item capture never returns an item-targeting
action with a null target.

Trigger vocabulary
==================
Timing always comes from a **weekday** word (monday…sunday) → next occurrence
3–4pm local; "due by <weekday>" is just a natural phrasing of the same weekday.
Event creation and a project's event/due-date REQUIRE a weekday.

New-item capture (no existing target) — self-contained proposals only:
  • **event word** (appointment/event/meeting/visit) **+ weekday**
        → ``create_event`` ONLY (standalone, timed). No work item.
  • anything else
        → ``create_work_item`` only.
  (An event word WITHOUT a weekday yields just ``create_work_item`` — there's no
   time to build an event from.)

Existing-item capture (real target_id) — item-targeting actions are valid:
  • **weekday** → ``set_due_date`` on the item.
  • **event word + weekday** → also a linked ``create_event``.
  • **done word** (done/finished/complete/completed) → ``complete_work_item``.
  • none of the above → ``no_action``.

Examples
--------
  "dentist appointment friday"     → create_event only (timed)
  "buy milk"                       → create_work_item only
  "team meeting"      (no weekday)  → create_work_item only
  "he is coming friday" (on item)  → set_due_date
  "all done"          (on item)    → complete_work_item
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.assistant.base import (
    AssistantClient,
    FocusedContext,
    ProposedAction,
)

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


def _next_weekday(ctx: FocusedContext, weekday: int, hour: int = 9) -> str:
    """The next occurrence of ``weekday`` at ``hour`` in the family tz, as UTC ISO."""
    tz = ZoneInfo(ctx.timezone)
    local_now = ctx.now.astimezone(tz)
    days = (weekday - local_now.weekday()) % 7
    days = days or 7  # "friday" said on a Friday means next Friday
    target = (local_now + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return target.astimezone(ZoneInfo("UTC")).isoformat()


class FakeAssistant(AssistantClient[FocusedContext]):
    def propose(self, ctx: FocusedContext) -> list[ProposedAction]:
        text = ctx.text.lower()
        tid = ctx.primary_work_item_id
        weekday = next((wd for name, wd in _WEEKDAYS.items() if name in text), None)
        event_word = any(w in text for w in _EVENT_WORDS)

        if tid is None:
            proposals = self._propose_new_item(ctx, weekday, event_word)
        else:
            proposals = self._propose_existing_item(ctx, tid, text, weekday, event_word)
        # The assistant describes what it understood. The fake just passes the
        # focused context through (a print) onto each proposal — per-action, so a
        # card is self-describing. A real assistant writes a genuine description.
        focus_note = ctx.render()
        for p in proposals:
            p.llm_rationale = focus_note
        return proposals

    # --- new-item capture: self-contained proposals only ------------------

    def _propose_new_item(
        self, ctx: FocusedContext, weekday, event_word: bool
    ) -> list[ProposedAction]:
        # Event word + weekday → event ONLY (no work item). Otherwise a work item.
        if event_word and weekday is not None:
            return [self._event(ctx, weekday, target_id=None, target_type="event")]

        return [
            ProposedAction(
                name="create_work_item",
                params={"title": ctx.text},
                llm_rationale="New capture — could be a work item.",
                target_id=None,
                target_type=None,
            )
        ]

    # --- existing-item capture: item-targeting actions are valid ----------

    def _propose_existing_item(
        self, ctx: FocusedContext, tid: int, text: str, weekday, event_word: bool
    ) -> list[ProposedAction]:
        proposals: list[ProposedAction] = []

        if weekday is not None:
            due = _next_weekday(ctx, weekday, hour=15)
            proposals.append(
                ProposedAction(
                    name="set_due_date",
                    params={"due_at": due},
                    llm_rationale="Detected a weekday in the text.",
                    target_id=tid,
                    target_type="work_item",
                )
            )
            if event_word:
                proposals.append(
                    self._event(ctx, weekday, target_id=tid, target_type="work_item")
                )

        if any(w in text for w in _DONE_WORDS):
            proposals.append(
                ProposedAction(
                    name="complete_work_item",
                    params={},
                    llm_rationale="Text mentions completion.",
                    target_id=tid,
                    target_type="work_item",
                )
            )

        if not proposals:
            proposals.append(
                ProposedAction(
                    name="no_action", params={}, llm_rationale="Nothing to suggest."
                )
            )
        return proposals

    # --- helpers ----------------------------------------------------------

    def _event(
        self, ctx: FocusedContext, weekday: int, *, target_id, target_type: str
    ) -> ProposedAction:
        """A fully-specified create_event (timed from the weekday, 3–4pm local)."""
        start = _next_weekday(ctx, weekday, hour=15)
        end = _next_weekday(ctx, weekday, hour=16)
        return ProposedAction(
            name="create_event",
            params={"title": ctx.text, "start_at": start, "end_at": end},
            llm_rationale="Looks like a scheduled event.",
            target_id=target_id,
            target_type=target_type,
        )
