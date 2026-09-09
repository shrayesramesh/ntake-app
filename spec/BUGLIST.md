# Bug list

**Owner:** shrayesr  
**Created:** 2026-09-04  
**Status:** Closed — live-validated 2026-09-08

This file records reproducible correctness incidents found during live UI
sessions. Product improvements and device-only checks belong in
[`UI_TESTING_BACKLOG.md`](UI_TESTING_BACKLOG.md). Reopen an entry only with a new
minimal reproduction and debug evidence; do not use this file as a backlog for
open-ended prompt tuning.

## Current status

There are no open correctness bugs. The former live-assistant incidents were
retested and validated after the family-local temporal-contract work. The next
MVP implementation task is observability for the capture → assistant → proposal
→ Confirm response flow; see [`PLAN.md`](PLAN.md).

## Closed incident record

| ID | Incident | Resolution and validated contract |
|---|---|---|
| BUG-000 | Llamafile ignored the constrained JSON schema. | `LocalLlmClient` sends the canonical JSON-schema response format; LINK and PROPOSE structured output is constrained. |
| BUG-001 | A new event about a linked household member omitted that person as a participant. | The participant rule is in the PROPOSE contract and the validated live capture includes the linked display name without overriding an explicit list. |
| BUG-002 | Relative weekday/clock interpretation produced the wrong day or time. | Timed tool values are offset-free family-local wall times; the trusted server timezone and DST-safe persistence boundary preserve the requested local time. |
| BUG-003 | LINK emitted an entity id absent from THE WORLD. | LINK is prompt-constrained to visible ids and server-side family whitelisting remains the defense in depth. The validated live capture no longer emitted the phantom id. |
| BUG-004 | Deep context mixed stored UTC values with family-local prompt context. | World and deep context render stored timed values in the family timezone; UTC is limited to the timed persistence boundary. |
| BUG-005 | EventCalendar title-first event content needed browser verification. | The intended month/week/day/device surfaces were visually validated with title, local time, participants, location, all-day behavior, and stable kiosk sizing. |
| BUG-006 | A timed event proposal could omit an end time. | Explicit timed/all-day action variants enforce `local_start_at` + `local_end_at` for timed events; all-day events retain local date defaults. |
| BUG-007 | A target-required proposal could render without a target and fail on Confirm. | Targetless modifiers are dropped; new lists use atomic `create_work_item` with optional initial checklist items. |
| BUG-008 | Deep context omitted checklist state and timestamped updates. | Deep context includes ordered checklist rows and family-local update timestamps. |

## Durable guardrails

- The assistant remains propose-and-confirm; no model output mutates data without
  an explicit Confirm.
- The model never selects a timezone. Timed action values are offset-free local
  values; UTC exists only at the database persistence boundary.
- Ambiguous and nonexistent DST wall times are rejected rather than silently
  choosing an offset or fold.
- Model-selected entity ids are always validated against the current family.
- Every rendered proposal must be independently executable; dependent proposal
  chains remain follow-on scope.
