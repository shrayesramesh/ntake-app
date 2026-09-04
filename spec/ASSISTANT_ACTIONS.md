# Assistant Actions — the LLM capability registry

> **Status:** BUILT (both fake + live local-LLM backends). The v1 toolset was
> seeded at 6 actions then **expanded to 16** for richer LLM context (status
> lifecycle, assignment, reschedule, archive, checklist, delete). Current v1 set:
> `set_due_date`, `complete_work_item`, `start_work_item`, `move_to_on_deck`,
> `move_to_todo`, `reopen_work_item`, `assign_work_item`, `archive_work_item`,
> `add_checklist_items`, `create_event`, `reschedule_event`, `delete_event`,
> `create_work_item`, `append_update`, `no_action`, `deconflict_events`. Each row's scope column
> below is the source of truth for what's built (**v1**) vs. backlog (v2 /
> deferred). This file remains the registry + scope reference; the live contract
> lives in `app/assistant/actions.py` (`ActionSpec.params`). Each spec also carries
> an optional pure `render_card(params, resolved)` that produces the proposal
> card's verbose, id-resolved detail lines (the app supplies the `resolved`
> member-name / target-label maps; the engine stays session-free).
>
> **Purpose.** The assistant (Phase 4) is a **planner over a fixed set of
> actions**. Its entire output is zero or more `{name, params}` objects drawn
> from the registry below. This file is the authoritative list of action **keys**
> and their **parameters** — the contract the LLM emits against, the schema we
> validate, the operations we apply on Confirm, and the cards the UI renders.
>
> **Design frame (from DESIGN §4.1, research/06):**
> - **Propose-and-confirm.** The assistant NEVER auto-applies. Each proposed
>   action renders as an inline Confirm/Dismiss card on the author's device.
>   Applying happens only on explicit Confirm.
> - **No suggestions table.** Proposed actions live only in the request/response;
>   unconfirmed ones vanish. Only confirmed *outcomes* persist: the field/row
>   change **plus** an appended `work_item_updates` row with `source=assistant`,
>   `author = confirming member`, narrating what happened.
> - **Extensible by construction.** Adding a capability = adding one entry to the
>   registry (its param model + apply fn + card text). The assistant prompt, the
>   validator, and the UI all iterate the registry generically. Unknown action
>   names or invalid params are dropped (graceful degradation).
> - **State-changing only.** Actions are confirmable *mutations*. Soft
>   interpretations (blocker / needs-help / partial progress) are NOT actions —
>   they are read-time summaries surfaced by the labor/board views (Phase 5),
>   per research/06 ("no `update_type` column; interpretation is transient").

## How to read this

The registry is **just a big dict** — `name → entry` — not a schema framework.
Each entry describes the action's params, what it changes, and how it's scoped.
`params` is a plain description of expected keys (validate lightly at apply time;
no formal per-action schema system required). Each action is one map entry:

```
"<action_name>": {
    params: { <name>: <type/constraint>, ... },
    applies_to: <what data-model change it makes>,
    on_confirm_also: append a source=assistant work_item_updates row IFF the
                     action targets a work item (conditional — see below),
    grounds: <requirement / data-model reference>,
    scope: v1 | v2 | deferred,
}
```

On Confirm, an action appends a `source=assistant` update row (WORKITEM-3)
**only when it targets a work item** (`target_type == "work_item"`). This was
originally described as universal; task 12 made it **conditional on the target**
so an action can target a work item, an event, or nothing. Event-only actions
(e.g. a standalone `create_event`) mutate the event and append **no** work-item
update — events aren't part of the labor log. It is omitted per-row below.

---

## The action registry (exhaustive candidate list)

### A. Work-item lifecycle & fields (verbose natural verbs)

Bias: **intent-shaped verbs** matching what a person would say; composites do
whatever field-writes are needed internally. Primitives kept only where there's
no cleaner verb.

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `set_due_date` | `work_item_id`, `due_at: datetime (UTC; resolved from relative text via families.timezone)` | sets `work_items.due_at`; item renders on the calendar | WORKITEM-8 | **v1** |
| `clear_due_date` | `work_item_id` | `due_at = NULL` (off the calendar) | WORKITEM-8 (inverse) | v2 |
| `start_work_item` | `work_item_id` | status → `doing` | WORKITEM-4 ("starting on it") | **v1** |
| `move_to_on_deck` | `work_item_id` | status → `on_deck` | WORKITEM-4 | **v1** |
| `move_to_todo` | `work_item_id` | status → `todo` | WORKITEM-4 | **v1** |
| `complete_work_item` | `work_item_id` | status → `done` **and** sets `completed_at` (composite — two writes) | WORKITEM-4; `completed_at` column | **v1** |
| `reopen_work_item` | `work_item_id` | status → `todo` (or prior), clears `completed_at` | WORKITEM-4 (inverse) | **v1** |
| `assign_work_item` | `work_item_id`, `member_id` | sets `assigned_to` | WORKITEM-7 | **v1** |
| `unassign_work_item` | `work_item_id` | `assigned_to = NULL` | WORKITEM-7 (inverse) | deferred |
| `tag_work_item` | `work_item_id`, `tags: [str]` | appends `work_items.tags` (shared vocab) | WORKITEM-9 / EVENT-6 | v2 |
| `untag_work_item` | `work_item_id`, `tags: [str]` | removes from `work_items.tags` | WORKITEM-9 (inverse) | deferred |
| `rename_work_item` | `work_item_id`, `title` | sets `title` | WORKITEM-1 | deferred |
| `append_to_description` | `work_item_id`, `text` | appends `description` | WORKITEM-1 | deferred |

> `set_status` (primitive) is intentionally REPLACED by the natural verbs above
> (`start_work_item` / `complete_work_item` / `move_to_*`) per the verbose-verbs
> preference — a small model emits "complete this" more reliably than
> `set_status(status="done")`, and `complete_work_item` also handles `completed_at`
> which a bare status write would miss.

### B. Work-item creation & the update log

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `create_work_item` | `title`, `description?`, `tags?: [str]`, `checklist_items?: [str]` | inserts `work_items` (status `todo`) and atomically seeds checklist rows when supplied | WORKITEM-1 / WORKITEM-6 (capture may be a new task or list) | **v1** |
| `append_update` | `work_item_id`, `body: str` (**assistant-composed** text) | appends a `work_item_updates` row (`source=assistant`) with NO other field change | WORKITEM-3/5 (record a blocker/observation as prose — the only in-model way, no column) | **v1** |

> **`add_note` vs. `append_update` — the `source` axis (WORKITEM-3):**
> - **`add_note`** = a **human-written** note — the casual thing a person does
>   ("let me add a note"). Its body is the *person's* prose, `source=human`. In
>   the capture flow the raw human input is **saved before the LLM runs**
>   (research/06) — so a human note is NOT an LLM action; it is the pre-LLM save.
>   It credits **human effort** in the labor view.
> - **`append_update`** = the **assistant-composed**, log-style entry the human
>   confirms. Its body is *LLM-generated*, `source=assistant`, `author=confirmer`.
>   It records an assistant-driven outcome, NOT human-authored effort.
> - `append_update` is the degenerate action whose *only* effect is an
>   assistant-sourced narration (a standalone assistant observation, no other
>   mutation). It is v1 because it preserves useful context without inventing a
>   new structured field.

### C. Checklist (grocery-list use case, WORKITEM-6) — full verb set

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `add_checklist_items` | `work_item_id`, `items: [str]` | inserts `checklist_items` rows | WORKITEM-6 ("add milk and eggs") | **v1** |
| `check_off_items` | `work_item_id`, `items: [str] \| item_ids: [int]` | sets `checked = true` | WORKITEM-6 ("we got the milk") | v2 |
| `uncheck_items` | `work_item_id`, `items \| item_ids` | sets `checked = false` | WORKITEM-6 (inverse) | deferred |
| `remove_checklist_items` | `work_item_id`, `items \| item_ids` | deletes `checklist_items` rows | WORKITEM-6 ("take bread off") | deferred |
| `reorder_checklist` | `work_item_id`, `ordered_item_ids: [int]` | sets `position` order | WORKITEM-6 | deferred |
| `clear_checked_items` | `work_item_id` | deletes all `checked` rows | WORKITEM-6 ("clear what we bought") | deferred |

### D. Calendar events (verbose verbs)

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `create_event` | `title`, one of `{start_at,end_at}` (timed UTC) OR `{start_date,end_date}` (all-day); `description?`, `location?`, `tags?: [str]`, `participants?: [{member_id?, name}]`; links `source_update_id` | inserts `events` row | ASSIST-3; EVENT-1/2/3/5/6/7 | **v1** |
| `deconflict_events` | `event_id` (target; the later-created of a same-start pair) | shifts the target event's timing pair (`start_at/end_at` or `start_date/end_date`) by +1 day; event-only (appends NO work-item update) | EVENT-1; calendar-context placeholder proving stage-1 `calendar_window` → action → apply (NOT smart scheduling) | **v1** |
| `reschedule_event` | `event_id`, new `{start_at,end_at}` or `{start_date,end_date}` | updates only the timing fields | EVENT-1 ("move the dentist to Thursday") | **v1** |
| `rename_event` | `event_id`, `title` | sets event `title` | EVENT-1 | deferred |
| `set_event_location` | `event_id`, `location` | sets `location` | EVENT-3 | deferred |
| `add_event_participants` | `event_id`, `participants: [{member_id?, name}]` | appends `participants` | EVENT-5 | deferred |
| `remove_event_participants` | `event_id`, `participants` | removes `participants` | EVENT-5 (inverse) | deferred |
| `tag_event` | `event_id`, `tags: [str]` | appends event `tags` | EVENT-6 | deferred |
| `untag_event` | `event_id`, `tags: [str]` | removes event `tags` | EVENT-6 (inverse) | deferred |
| `make_event_all_day` | `event_id`, `start_date`, `end_date` | switches timed→all-day (moves timing to date fields; clears start_at/end_at) | EVENT-2 (avoid off-by-one) | deferred |
| `make_event_timed` | `event_id`, `start_at`, `end_at` | switches all-day→timed | EVENT-2 (inverse) | deferred |
| `cancel_event` | `event_id` | deletes an `events` row | EVENT-1 (delete); SAFE-2 (destructive → extra confirm) | deferred |
| `link_event_to_item` | `event_id`, `source_update_id` | sets `events.source_update_id` | EVENT-7 / ACCESS-4 | deferred |

### E. Grooming / archive (GROOM) — *needs GROOM built (currently read-only board)*

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `archive_work_item` | `work_item_id` | sets `archived_at` (invariant: only `done` may be archived) | GROOM-2/4 | **v1** (assistant action; board UI is Phase 5) |
| `unarchive_work_item` | `work_item_id` | clears `archived_at` | GROOM-3 | deferred |
| `archive_all_done` | *(none)* | archives every `done` item | GROOM-3 | deferred |

### F. Relational / grooming-adjacent

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `merge_work_items` | `keep_id`, `merge_ids: [int]` | moves updates/checklist to `keep_id`, archives/deletes others | grooming need ("these are the same") | deferred |
| `split_work_item` | `work_item_id`, `new_titles: [str]` | creates sibling items | grooming need | deferred |
| `propose_recurring_series` | `template`, `cadence`, `count\|until` | creates N discrete `events` (no RRULE column) | EVENT-4 | deferred |

### G. Meta

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `no_action` | *(none)* | nothing — the model's valid "I have no suggestion" output | reliability: gives a small model a legitimate empty result instead of hallucinating one | **v1** |

---

## NOT actions (deliberately)

Read-time interpretations, not confirmable mutations — surfaced by the
labor/board views (Phase 5), never stored as classifications (research/06):

- **blocker / needs-more-info**, **request-for-help**, **multi-step / partial
  progress** — surfaced from the log when relevant (WORKITEM-5). *(The only
  in-model way to record one is `append_update` as assistant prose — not a
  column.)*

Excluded write actions (would violate a design stance):
- Anything that **auto-applies** without confirm — forbidden (ASSIST-2).
- A **persisted labor score / ranking** — forbidden (R-labor guardrail).
- **Member/device management** (enroll/revoke) — operator CLI only (ACCESS-1).

---

## v1 cut — LOCKED

## v1 cut — the built toolset (seeded at 6, now 16)

The v1 was **seeded** with the 6 below (the minimal architecture-proving set),
then expanded to its current **16 actions** as richer prompt context and explicit
confirmable mutations proved useful. Everything still-unbuilt in the registry is
a pre-shaped slot (add later by registering the entry — no rework of the flow).

**Seed 6 (the original locked cut):**

1. **`set_due_date`** — flagship assistant field (WORKITEM-8); first real use of
   `families.timezone` for relative-date resolution.
2. **`create_event`** — the calendar bridge (ASSIST-3); exercises `source_update_id`.
3. **`complete_work_item`** — the most common lifecycle verb; composite
   (status=done + completed_at), showing why verbose verbs beat bare `set_status`.
4. **`create_work_item`** — the "this is a new thing" capture branch (WORKITEM-1).
5. **`deconflict_events`** — calendar-context placeholder (event-only): proves the
   stage-1 `calendar_window` flows into an executable, event-targeting action and
   applies. Not smart scheduling — it moves the later-created of a same-start pair
   by +1 day.
6. **`no_action`** — reliability primitive so a small model can say "nothing."

**Subsequent additions (richer context for prompt engineering):**

7. **`start_work_item` / `move_to_on_deck` / `move_to_todo` / `reopen_work_item`**
   — the rest of the status lifecycle, so the model reasons over the whole 4-state
   board, not just todo/done.
8. **`assign_work_item`** — first **whitelist-validated context id** (`member_id`
   must be a real family member, else ActionError); makes members-in-context
   actionable.
9. **`reschedule_event`** — first **modify-existing** action (non-null event
   target); exercises create-vs-modify disambiguation.
10. **`archive_work_item`** — done-only invariant (ActionError otherwise). The
    assistant action is built; the board's manual grooming UI is Phase 5.
11. **`add_checklist_items`** — the easy grocery-list slice (`items: [str]`);
    check/uncheck/remove deferred (they need by-name/by-id addressing).
12. **`delete_event`** — explicit event-only cancellation/deletion, kept separate
    from work-item log attribution.
13. **`append_update`** — assistant-composed context for an existing resolved
    work item; it records an observation without changing status, due date, or
    checklist state.

**v1 boundaries (explicit):**
- Capture targets an **explicit work item** for item-scoped actions — assistant
  routing of free text to the right existing item is v2 (OQ-A2).
  `create_work_item` covers the new-item branch.
- All actions are **propose-and-confirm** (ASSIST-2); a confirmed action
  also appends a `source=assistant` update **when it targets a work item**
  (conditional rule, task 12 — a standalone event appends nothing).
- Lightweight param checks at apply time (the registry entry lists expected
  keys); invalid/unknown actions are dropped, the raw human input is still saved
  (graceful degradation, OQ-A3).


## Open questions

- **OQ-A1** Confirm granularity: one action per card, each independently
  confirmable (per ASSIST-2). Since actions aren't persisted, the Confirm payload
  IS the action object the client sends back. Endpoint shape TBD.
  - **v1 rule — every proposal FULLY DEFINES its operation.** A returned proposal
    must be executable in isolation: a targeting action references a real,
    existing `target_id` (+ `target_type`); a creating action fully specifies the
    new entity in its params. Capture never returns an item-targeting action with
    a null target. Consequence: a brand-new item's due date is NOT a second card
    on a new-item capture (there's no item yet) — the new item is proposed via
    `create_work_item`, and its due date is set later by capturing onto it once it
    exists (correct-by-restate). Each proposal carries a batch-local
    **`proposal_id`** (e.g. "p1"), a stable handle within one response.
  - **`target_id` is a CREATE-vs-MODIFY distinction.** `target_id` is the id of an
    **existing** entity the action modifies. A *create* action has nothing
    existing to point at, so `target_id=None` and the new row's id is assigned on
    Confirm: a standalone `create_event` is `target_type="event"`, `target_id=None`
    (fully defined by its params); a `create_event` *from* a work item is
    `target_type="work_item"`, `target_id=<work item id>` (links back + logs). A
    future *modify* action (`reschedule_event`) would be `target_type="event"` with
    a **non-null** `target_id=<existing event id>`. So `target_type="event"` does
    double duty (what the action concerns vs. an existing event it modifies) —
    keyed by whether `target_id` is set. The "fully defines its operation" check is
    therefore: a `work_item` target must have a concrete `target_id`; a standalone
    create is defined by its params.
  - **v2 (deferred) — dependency chaining via `target_ref`.** A proposal could
    reference another proposal's to-be-created entity by its `proposal_id`
    (`target_ref="p1"`), letting "create item" + "set its due date" come back as
    two independent cards. Gating: the dependent card is **disabled until its
    referent is confirmed** (the confirm response returns the created entity's
    real id/type, which the client resolves into the dependent card's target),
    backed by the **server rejecting an unresolved target with 422** (defense in
    depth — the UI gate is convenience, the server is the guarantee). This is
    generic engine behavior and belongs with the propose-confirm engine
    extraction, not the ntake plugin. `target_ref` is reserved in the shape now
    and MUST be None in v1.
- **OQ-A2 — resolved (2026-09-04).** The assistant chooses
  `create_work_item` for a new task/list and `append_update` only when LINK
  resolved an existing work item. The proposal parser enforces that every
  target-required action has a concrete resolved target, so an unexecutable
  modifier never reaches the card UI.
- **OQ-A3** Param validation strictness for a small local model — lightweight
  checks against the registry entry's expected keys (a plain dict, not a schema
  framework); on failure, drop the action (don't fail the whole capture).
- **OQ-A4 — resolved (2026-09-04).** `append_update` is a built
  assistant-composed, independently confirmable log-only action. It remains
  distinct from every other action's outcome narration because it records useful
  context without another field or row mutation.
