"""``LocalLlmAssistant`` — the PROPOSE call (LLM call 2).

Stage-2 seam (:class:`AssistantClient`) backed by a real model. It composes the
already-built pieces — ``build_propose_prompt`` (the prompt) + ``build_tools_schema``
(the constrained-output schema) — calls the injected :class:`LLM` seam, then turns
the reply into ``[ProposedAction]``: parse the actions array, keep only calls
that name a registered action **and** whose params satisfy that action's contract
(``ActionSpec.accepts`` — required present + exactly one exclusive group), and
attach the server-known target from the resolved ids in the ``FocusedContext``.

The model emits **id-free** ``{name, params}``; ids never come from the model. The
target is attached here (LLD OQ-4, v1): type-based, ≤1 resolved entity per type,
driven by the action's declared ``ActionSpec.target_type`` (the single source both
assistants read) — ``"work_item"`` → the primary work-item id, ``"event"`` → the
primary event id, ``None`` (a creator / ``no_action``) → no target.

Depends on the ``LLM`` protocol, never on httpx. Parse here is deliberately
lenient (drop what doesn't fit) so a sloppy model degrades to fewer/zero
proposals rather than raising; the exhaustive adversarial hardening is step 6.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.assistant.actions import REGISTRY
from app.assistant.capture import FocusedContext, ProposedAction
from app.assistant.local_llm.protocol import LLM
from app.assistant.local_llm.tools_schema import build_tools_schema
from app.assistant.prompts import build_propose_prompt
from app.assistant.tools_view import build_tools_view
from app.models import TargetType
from app.routing.engine import ActionRegistry, AssistantClient

_EVENT_TIMING_ACTIONS = frozenset({"create_event", "reschedule_event"})
_WEEKDAY_NUMBERS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
_WEEKDAY_PATTERN = re.compile(
    r"\b(" + "|".join(_WEEKDAY_NUMBERS) + r")\b", re.IGNORECASE
)
_TIME_RANGE_PATTERN = re.compile(
    r"\b(?P<start_hour>1[0-2]|0?[1-9])(?::(?P<start_minute>[0-5]\d))?"
    r"\s*(?:-|–|to)\s*"
    r"(?P<end_hour>1[0-2]|0?[1-9])(?::(?P<end_minute>[0-5]\d))?"
    r"\s*(?P<period>a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)
_TIME_PATTERN = re.compile(
    r"\b(?P<hour>1[0-2]|0?[1-9])(?::(?P<minute>[0-5]\d))?"
    r"\s*(?P<period>a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)


def _matches_explicit_event_timing(
    name: str, params: dict, ctx: FocusedContext
) -> bool:
    """Reject event timing that contradicts an explicit weekday/clock claim.

    The model remains responsible for interpreting ordinary prose. This guard only
    checks the unambiguous pieces it can read deterministically: a named weekday
    means its next occurrence in the family timezone, and an AM/PM clock claim
    must round-trip from the emitted UTC timestamp. It drops a contradiction
    instead of silently rewriting model output.
    """
    if name not in _EVENT_TIMING_ACTIONS:
        return True

    expected = _explicit_local_timing(ctx)
    if expected is None:
        return True
    expected_date, expected_start, expected_end = expected

    start_at = params.get("start_at")
    if not isinstance(start_at, str):
        # An all-day event can satisfy a bare weekday, but not an explicit clock.
        return (
            expected_start is None
            and expected_end is None
            and params.get("start_date") == expected_date.isoformat()
        )

    start = _parse_utc_datetime(start_at)
    if start is None:
        return False
    local_start = start.astimezone(ZoneInfo(ctx.timezone))
    if local_start.date() != expected_date:
        return False
    if expected_start is not None and local_start.time() != expected_start:
        return False

    if expected_end is None:
        return True
    end_at = params.get("end_at")
    if not isinstance(end_at, str):
        return False
    end = _parse_utc_datetime(end_at)
    if end is None:
        return False
    return end.astimezone(ZoneInfo(ctx.timezone)).time() == expected_end


def _explicit_local_timing(
    ctx: FocusedContext,
) -> tuple[date, time | None, time | None] | None:
    weekday_match = _WEEKDAY_PATTERN.search(ctx.text)
    if weekday_match is None:
        return None

    zone = ZoneInfo(ctx.timezone)
    aware_now = ctx.now.replace(tzinfo=UTC) if ctx.now.tzinfo is None else ctx.now
    local_now = aware_now.astimezone(zone)
    weekday = _WEEKDAY_NUMBERS[weekday_match.group(1).lower()]
    days = (weekday - local_now.weekday()) % 7 or 7
    expected_date = (local_now + timedelta(days=days)).date()

    range_match = _TIME_RANGE_PATTERN.search(ctx.text)
    if range_match is not None:
        period = range_match.group("period")
        return (
            expected_date,
            _clock_time(
                range_match.group("start_hour"),
                range_match.group("start_minute"),
                period,
            ),
            _clock_time(
                range_match.group("end_hour"),
                range_match.group("end_minute"),
                period,
            ),
        )

    time_match = _TIME_PATTERN.search(ctx.text)
    if time_match is not None:
        return (
            expected_date,
            _clock_time(
                time_match.group("hour"),
                time_match.group("minute"),
                time_match.group("period"),
            ),
            None,
        )
    return expected_date, None, None


def _clock_time(hour_text: str, minute_text: str | None, period: str) -> time:
    hour = int(hour_text)
    if hour == 12:
        hour = 0
    if period.lower().replace(".", "") == "pm":
        hour += 12
    return time(hour, int(minute_text or 0))


def _parse_utc_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


class LocalLlmAssistant(AssistantClient[FocusedContext]):
    """Propose actions for a focused context via one constrained LLM call."""

    def __init__(self, llm: LLM, registry: ActionRegistry = REGISTRY) -> None:
        self._llm = llm
        self._registry = registry

    def propose(self, ctx: FocusedContext) -> list[ProposedAction]:
        system, user = build_propose_prompt(
            tools_view=build_tools_view(self._registry),
            deep_context=ctx.deep_context,
            note=ctx.text,
            now=ctx.now,
            timezone=ctx.timezone,
        )
        schema = build_tools_schema(self._registry)
        reply = self._llm.complete(system=system, user=user, schema=schema)
        proposals: list[ProposedAction] = []
        for call in _parse_actions(reply):
            spec = self._registry.get(call["name"])
            # Drop unknown actions and calls that don't satisfy the spec's param
            # contract (missing required / wrong exclusive-group) — graceful
            # degrade to fewer proposals, never a raise (LLD OQ-5).
            if (
                spec is None
                or not spec.accepts(call["params"])
                or not _matches_explicit_event_timing(call["name"], call["params"], ctx)
            ):
                continue
            proposal = self._attach(call, ctx)
            if spec.needs_target and proposal.target_id is None:
                continue
            proposals.append(proposal)
        return proposals

    def _attach(self, call: dict, ctx: FocusedContext) -> ProposedAction:
        """Turn a validated ``{name, params}`` into a targeted ProposedAction.

        The target category comes from the action's declared
        ``ActionSpec.target_type`` (single source): ``"work_item"`` → the primary
        resolved work-item id, ``"event"`` → the primary resolved event id,
        ``None`` (a creator / no_action) → no target. Ids come from the context,
        never the model.
        """
        name = call["name"]
        spec = self._registry.get(name)
        target_type = spec.target_type if spec is not None else None
        target_id: int | None = None
        if target_type == TargetType.WORK_ITEM:
            target_id = ctx.primary_work_item_id
        elif target_type == TargetType.EVENT:
            target_id = ctx.primary_event_id
        return ProposedAction(
            name=name,
            params=call["params"],
            target_id=target_id,
            target_type=target_type,
        )


def _parse_actions(reply: dict) -> list[dict]:
    """Extract the ``{name, params}`` tool calls from the model reply.

    Tolerant of untrusted output: a missing/non-list ``actions`` → ``[]``; each
    entry must be a dict with a string ``name`` (``params`` defaults to ``{}`` and
    must be a dict). Anything malformed is dropped (graceful-degrade; step 6
    tightens the adversarial cases).
    """
    actions = reply.get("actions")
    if not isinstance(actions, list):
        return []
    calls: list[dict] = []
    for entry in actions:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        params = entry.get("params", {})
        if not isinstance(name, str) or not isinstance(params, dict):
            continue
        calls.append({"name": name, "params": params})
    return calls
