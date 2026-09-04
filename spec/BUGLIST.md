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

## Open

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
{"participants": [{"member_id": 2}]}
```

The member-linking pipeline already resolves Sam and supplies his workload to
PROPOSE; the confirmed event should preserve that attribution unless the model or
user explicitly indicates another participant set.

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

Decide the deterministic contract: for `create_event`, should the app inject
`ctx.primary_member_id` as a participant when `params.participants` is absent, or
should the prompt require the model to emit the member id? Prefer a testable,
explicit rule that does not overwrite an explicitly supplied participant list.

---

### BUG-002 — relative weekday and local-time conversion are wrong — open

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

**Investigation direction**

Strengthen the PROPOSE prompt's calendar arithmetic instruction and add a
small deterministic date/time helper or validation layer if prompt-only tuning
is not reliable. Do not silently "correct" ambiguous dates without a documented
rule; the proposal card must make the resolved human date/time obvious before
Confirm.

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

### BUG-004 — deep context renders UTC timed events without a UTC label — open

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

**Investigation direction**

Choose one representation for model context: preferably render deep-context event
times in the family timezone, matching WorldView; alternatively retain UTC but
append `UTC` to every timed value and make the prompt explicit. Add a snapshot test
covering the chosen label/zone behavior.

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


### BUG-005 — EventCalendar default event card leads with time and drops context — open

**Class:** UI integration  
**Severity:** medium (calendar remains correct but is less informative than the
replaced agenda cards)

**Reproduction**

Open the EventCalendar month/week/day grid after the first integration. The
library's default event rendering leads with `timeText`, then title, and omits the
participant/location context previously visible in the agenda event cards.

**Expected**

A compact grid event should lead with the event title, followed by small metadata
when available: local time for timed events, participant names, and location. The
month grid should remain dense; full description belongs in a later detail
popover, not every cell.

**Observed**

The default library card leads with the time and appears less informative than the
previous app-rendered event cards.

**Investigation direction**

Use EventCalendar's `eventContent` callback with safe DOM nodes; enrich the
existing authenticated `/events` DTO with resolved `participant_names` so the
client never renders member ids (`m2`). Keep EventCalendar read-only.


### BUG-006 — timed create_event with only start_at persists no end — open

**Class:** code / action-contract mismatch  
**Severity:** medium (proposal is reviewable, but confirmed event duration is
underspecified)

**Reproduction**

For `sam meal prep wed 1pm`, PROPOSE emitted:

```json
{
  "name": "create_event",
  "params": {"title": "Sam meal prep", "start_at": "2026-09-08T13:00:00Z"}
}
```

`ActionSpec.accepts()` treats `start_at` as the timed exclusive-group anchor, so
this proposal is valid. `_apply_create_event` currently persists `end_at=None`
when it is absent. EventCalendar then falls back to the start, rendering a
zero-duration/point event.

**Expected**

Choose and enforce one explicit contract:

- require `end_at` for a timed create, or
- default `end_at` to `start_at` (point event), or
- default a documented duration suitable for household events.

The contract should match `reschedule_event`, which already defaults a missing
end to the start, and the verbose proposal card should disclose the resulting
duration before Confirm.
