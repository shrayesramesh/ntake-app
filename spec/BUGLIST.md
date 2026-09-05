# Bug list

**Owner:** shrayesr  
**Created:** 2026-09-04  
**Status:** Active

This is the reproducible correctness/behavior bug list found during live UI
sessions. Use `spec/UI_TESTING_BACKLOG.md` for product improvements and interaction
requests; use this file when observed behavior violates a contract, produces an
incorrect proposal, or exposes an unsafe/ambiguous context.

## Triage conventions

| Field | Meaning |
|---|---|
| Status | `open` · `investigating` · `fixed` · `wontfix` |
| Class | `code` · `prompt/model` · `data` · `integration` |
| Severity | `high` changes/persists the wrong household data; `medium` proposes wrong data but Confirm catches it; `low` is diagnostic/presentation-only |

A bug entry should carry a minimal reproduction, expected/observed result, and
relevant raw debug evidence. Model-quality findings still belong here when the
app can improve the prompt, validation, or deterministic post-processing.

---

## Active / awaiting live verification

### BUG-001 — linked member is not attached to a new event — open

**Class:** code / prompt-contract integration
**Severity:** medium (proposal is reviewable before Confirm)

**Reproduction**

- Capturing member: Alex (`m1`)
- Note: `soccer game for sam wednesday 5-6`
- LINK raw reply: `{"work_item_ids": [], "event_ids": [5], "member_ids": [2]}`
- Deep context: `ALSO ABOUT: [m2] Sam (adult)`
- PROPOSE action: `create_event` for `soccer game`

**Expected**

A new event about Sam should carry the resolved participant:

```json
{"participants": ["Sam"]}
```

The member-linking pipeline already resolves Sam and supplies his workload to
PROPOSE; the model should emit Sam's display name when creating an event about
him unless the user explicitly indicates another participant set.

**Observed**

The model emitted no `participants` field. The proposed event would lose Sam's
participant link even though LINK identified him.

**Second reproduction**

- Note: `sam meal prep wed 1pm`
- Context: `ALSO ABOUT: [m2] Sam (adult)`
- PROPOSE: `create_event` titled `Sam meal prep`, again with no `participants`.

This confirms the gap is not specific to soccer phrasing; member linking reaches
context, but no deterministic/create-event attribution contract consumes it.

**Investigation direction**

Decide the prompt contract: should it require the model to emit the linked
member's display name when creating an event about them? Prefer a testable,
explicit rule that does not overwrite an explicitly supplied participant list.

---

### BUG-002 — relative weekday and local-time conversion are wrong — fixed (test-verified; live retest pending)

**Class:** prompt/model with deterministic context contribution  
**Severity:** high (Confirm could persist an event at the wrong time/day)

**Reproduction**

- Family timezone: `America/New_York`
- Prompt clock: Friday 2026-09-04
- Note: `soccer game for sam wednesday 5-6`

**Expected**

The next Wednesday is 2026-09-09. A 5–6 PM New York event should be emitted as:

```json
{
  "start_at": "2026-09-09T21:00:00Z",
  "end_at": "2026-09-09T22:00:00Z"
}
```

**Observed**

The model emitted:

```json
{
  "start_at": "2026-09-07T17:00:00Z",
  "end_at": "2026-09-07T18:00:00Z"
}
```

That is Monday, not Wednesday, and 1–2 PM New York, not 5–6 PM.

**Second reproduction**

- Note: `sam meal prep wed 1pm`
- Expected: Wednesday 2026-09-09 at 1 PM New York = `2026-09-09T17:00:00Z`
  (with a deliberate end-time/default-duration policy).
- Observed: only `start_at: "2026-09-08T13:00:00Z"` — Tuesday at 9 AM New
  York, and no `end_at`.

The repeated one-day/timezone error indicates a prompt/model behavior problem,
not a single ambiguous phrasing.

**Fix (2026-09-04)**

The PROPOSE prompt now provides both the UTC instant and the explicit family-local
clock/date (including weekday), and requires the model to round-trip emitted UTC
times back to the requested local weekday and clock time. The local-LLM proposal
parser independently drops explicit timed/all-day event variants that contradict
contradict an explicit weekday and/or AM/PM time in the note. It does not silently
rewrite model output or invent a time for ambiguous prose.

Regression tests cover both incident shapes: a wrong Wednesday 5–6 PM event and
a wrong `wed 1pm` event are dropped; the correctly converted Wednesday 5–6 PM
proposal remains confirmable. Re-run the live trace to verify model behavior now
uses the strengthened prompt rather than needing the guard.

---

### BUG-003 — LINK returns event ids absent from THE WORLD — open

**Class:** prompt/model contract violation  
**Severity:** low while family whitelist remains in place; medium if validation is
removed or weakened

**Reproduction**

For the same `soccer game for sam wednesday 5-6` capture, THE WORLD exposed only
events `e1` through `e4`, but LINK emitted `event_ids: [5]`.

**Expected**

A brand-new soccer event should link no existing event:

```json
{"event_ids": []}
```

The LINK prompt explicitly says to reference only ids present in THE WORLD.

**Observed / current safety behavior**

The raw model reply includes nonexistent `e5`. `resolve_ids` family-whitelists
ids before they reach `FocusedContext`, so this id is dropped and does not become
an attachable target. The result is safe today, but the model contract is violated
and it adds noise to debug reasoning.

**Investigation direction**

Prompt-tune LINK toward fewer ids when unsure; retain the server-side whitelist as
the non-negotiable defense. Add a regression test around raw out-of-world ids being
dropped if one does not already cover this exact member/event combination.

---

### BUG-004 — deep context renders UTC timed events without a UTC label — fixed (test-verified; live retest pending)

**Class:** code / prompt-context ambiguity  
**Severity:** medium (can contribute to incorrect model time arithmetic)

**Reproduction**

In the incident trace, the shallow WorldView rendered the dentist as `Fri Sep 4,
5:37 PM` in the family timezone (`America/New_York`). The deep context rendered
the same event as `Fri Sep 4, 9:37 PM` but did not say `UTC`.

**Expected**

Every time shown to the model carries an explicit timezone, or all model context
uses one consistent family-timezone representation.

**Observed**

`deep_context._fmt_dt` intentionally formats stored UTC, but its output omits a
zone suffix while the PROPOSE prompt says relative dates/times should be resolved
in the family timezone. The model receives two conflicting-looking times with no
explanation.

**Fix (2026-09-04)**

`deep_context` now resolves the household timezone and renders every timed event
(and timed work-item due value) in that same family-local representation used by
WorldView. SQLite's tz-naive readback is still attached to UTC before conversion.
A regression test proves `2026-09-04T21:37:00Z` renders as `5:37 PM` in
`America/New_York`, not `9:37 PM`.

---

### BUG-005 — EventCalendar title-first cards need browser verification — investigating

**Class:** UI integration  
**Severity:** medium (calendar data remains correct; the gap is presentation and
browser behavior)

**Current state**

The documented EventCalendar implementation now renders title-first cards with
local time, participant names, and location when present. `README.md` and `PLAN.md` describe this code as landed, but it has not been visually
verified on the intended month/week/day and device surfaces.

**Expected**

A compact grid event leads with the event title, followed by small local-time,
participant, and location metadata when available. The month grid remains dense;
full description belongs in a later detail popover, not every cell.

**Verification direction**

Check the rendered month/week/day cards in the live UI, including all-day events,
participant names rather than member ids, location display, and the kiosk-height
constraint. Change implementation only if that visual verification finds a
mismatch.

---

### BUG-006 — timed create_event with only start_at persists no end — fixed (test-verified; live retest pending)

**Class:** code / action-contract mismatch
**Severity:** medium (proposal was reviewable, but confirmed event duration was
underspecified)

**Reproduction**

For `sam meal prep wed 1pm`, PROPOSE emitted the overloaded `create_event` with
only `start_at`. Its exclusive timing contract accepted the start anchor, while
the apply handler persisted `end_at=None`.

**Fix (2026-09-04)**

The overloaded `create_event` and `reschedule_event` actions were replaced with
explicit timed/all-day variants. `create_timed_event` and
`reschedule_timed_event` both require `start_at` **and** `end_at`.
`create_all_day_event` and `reschedule_all_day_event` require `start_date` and
default an omitted `end_date` to the start date. No current ntake action uses
per-action `exclusive_params`; the generic engine support remains available for
future consumers.

---

### BUG-007 — targetless checklist/status proposals render but cannot confirm — fixed (test-verified; live retest pending)

**Class:** code / prompt-contract integration
**Severity:** medium (Confirm rejects the change before persistence, but presents a
broken action card)

**Reproduction**

- Capturing member: Alex (`m1`)
- Note: `alex is getting the dress tomorrow`
- LINK/PROPOSE context: no relevant work items; only unrelated sample events
- PROPOSE raw reply:

```json
{
  "actions": [
    {
      "name": "add_checklist_items",
      "params": {"items": ["dress"]}
    }
  ]
}
```

`add_checklist_items` requires an existing work-item target. The local proposal
attachment step has no `primary_work_item_id`, so it returns this proposal with
`target_type: "work_item"` and `target_id: null`. The UI still renders its card.
Confirming it reaches the work-item handler, which rejects it with `422: work item
not found: None`; the UI only appends `(failed)`.

The same root behavior appeared in two additional captures with no resolved work
item:

- `pack for pittsburg trip thurs morning` produced `add_checklist_items` plus
  `move_to_on_deck` while the context contained an event but no work item.
- `grocery list for the week` produced `add_checklist_items` with
  `["grocery list for the week"]` as its sole item despite no target work item.

All of these cards are targetless and cannot confirm.

**Expected**

No proposal that requires an existing target may be rendered unless the resolver
attached a real target id. A new-item capture can instead propose a fully-defined
`create_work_item`; a checklist action belongs only after that work item exists.
A future dependent-card flow would require explicit `target_ref` chaining and a
server-side unresolved-target rejection.

**Observed**

The schema accepts the action's parameters, but proposal construction does not
validate the separate target contract. This displays a non-executable card despite
the v1 requirement that every targeting proposal be independently confirmable.

**Decision (2026-09-04)**

Keep the v1 invariant that every rendered card is independently confirmable. For
a new list with supplied entries, extend `create_work_item` with optional
`checklist_items: [string]`. Its one Confirm operation atomically creates the
work item and its initial checklist rows. This is a cohesive composite action,
like `complete_work_item` setting both status and completion time; it does not
make a second proposal depend on an unconfirmed first proposal.

Multiple cards remain valid only when they are independent. Do not emit
`create_work_item` plus `add_checklist_items` as ordinary v1 cards: the latter
has no real target until the first card is confirmed. The deferred `target_ref`
dependency-chaining design is the future option if that workflow is desired.

**Fix (2026-09-04)**

The local proposal parser now drops every action whose `ActionSpec.needs_target`
is true but has no same-type resolved target id. The PROPOSE prompt explicitly
separates creation from modification: a note with no relevant work item may use
`create_work_item` (or `no_action`), never a work-item modifier; event modifiers
likewise require an existing resolved event.

`create_work_item` now accepts optional `checklist_items`. One Confirm atomically
creates the standalone work item and its initial checklist rows; a title alone
still creates an ordinary task with no checklist. The action schema, tool view,
proposal card, and action reference document this contract. Regression tests cover
targetless checklist/status actions being dropped, the complete create-with-list
path, empty-list rejection, the prompt rule, and the rendered card. Re-run the
three live captures to verify the model follows the strengthened prompt.

---

### BUG-008 — deep context omitted full checklists and update timestamps — fixed (test-verified; live retest pending)

**Class:** code / prompt-context completeness
**Severity:** medium (the model could not reason over checklist state or update
recency for an existing work item)

**Reproduction**

A newly created `Pittsburgh Planning` item with three checklist entries rendered
only its assistant summary update:

```text
RELEVANT WORK ITEMS:
- [w1] Pittsburgh Planning (todo)
    · [assistant] Created work item: Pittsburgh Planning with 3 checklist item(s)
```

The actual checklist rows, their checked state, position, and the update's native
`created_at` value were missing from the model context.

**Fix (2026-09-04)**

Deep context now renders each item's full checklist in `position` order before
its updates, using `[ ]` and `[x]` state markers. It renders every update's native
`created_at` in the family timezone (`[source · local timestamp]`) and omits
empty `CHECKLIST:` / `UPDATES:` headings. Regression tests cover order, state,
localized timestamps, section order, and empty items.

---

## Fixed

### BUG-000 — constrained JSON schema was silently ignored by llamafile — fixed

**Class:** code / integration
**Fixed:** 2026-09-04

`LocalLlmClient` used flat `response_format.schema`, which this llamafile build
silently ignored. LINK returned `{}`/free-form replies, so targets were unresolved
and requests such as "move the dentist to Wednesday" degraded to `create_event`.

The client now sends canonical `response_format.json_schema.{name, schema}`;
llamafile enforces it. Live verification: "move the dentist to Friday" produces
`reschedule_event` on the resolved dentist event. The family whitelist remains the
second defense against model-supplied ids.
