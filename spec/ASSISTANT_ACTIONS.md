# Assistant Actions — the LLM capability registry

> **Status:** vocabulary drafted; **v1 cut is LOCKED** (see "v1 cut — LOCKED"
> below): `set_due_date`, `create_event`, `complete_work_item`,
> `create_work_item`, `no_action`.
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
    on_confirm_also: append a source=assistant work_item_updates row (always),
    grounds: <requirement / data-model reference>,
    scope: v1 | v2 | deferred,
}
```

Every action, on Confirm, appends a `source=assistant` update row (WORKITEM-3) —
that is universal and omitted per-row below.

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
| `start_work_item` | `work_item_id` | status → `doing` | WORKITEM-4 ("starting on it") | v2 |
| `move_to_on_deck` | `work_item_id` | status → `on_deck` | WORKITEM-4 | v2 |
| `move_to_todo` | `work_item_id` | status → `todo` | WORKITEM-4 | v2 |
| `complete_work_item` | `work_item_id` | status → `done` **and** sets `completed_at` (composite — two writes) | WORKITEM-4; `completed_at` column | **v1** |
| `reopen_work_item` | `work_item_id` | status → `todo` (or prior), clears `completed_at` | WORKITEM-4 (inverse) | v2 |
| `assign_work_item` | `work_item_id`, `member_id` | sets `assigned_to` | WORKITEM-7 | v2 |
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
| `create_work_item` | `title`, `description?`, `tags?: [str]`, `assigned_to?` | inserts `work_items` (status `todo`) | WORKITEM-1 (capture may be a *new* item) | **v1** |
| `append_update` | `work_item_id`, `body: str` (**assistant-composed** text) | appends a `work_item_updates` row (`source=assistant`) with NO other field change | WORKITEM-3/5 (record a blocker/observation as prose — the only in-model way, no column) | v2 |

> **`add_note` vs. `append_update` — the `source` axis (WORKITEM-3):**
> - **`add_note`** = a **human-written** note — the casual thing a person does
>   ("let me add a note"). Its body is the *person's* prose, `source=human`. In
>   the capture flow the raw human input is **saved before the LLM runs**
>   (research/06) — so a human note is NOT an LLM action; it is the pre-LLM save.
>   It credits **human effort** in the labor view.
> - **`append_update`** = the **assistant-composed**, log-style entry the human
>   confirms. Its body is *LLM-generated*, `source=assistant`, `author=confirmer`.
>   It records an assistant-driven outcome, NOT human-authored effort.
> - Note that **every** confirmed action already appends a `source=assistant`
>   narration (universal rule), so `append_update` is the degenerate action whose
>   *only* effect is that narration (a standalone assistant observation, no
>   mutation). Hence v2, not v1.

### C. Checklist (grocery-list use case, WORKITEM-6) — full verb set

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `add_checklist_items` | `work_item_id`, `items: [str]` | inserts `checklist_items` rows | WORKITEM-6 ("add milk and eggs") | v2 |
| `check_off_items` | `work_item_id`, `items: [str] \| item_ids: [int]` | sets `checked = true` | WORKITEM-6 ("we got the milk") | v2 |
| `uncheck_items` | `work_item_id`, `items \| item_ids` | sets `checked = false` | WORKITEM-6 (inverse) | deferred |
| `remove_checklist_items` | `work_item_id`, `items \| item_ids` | deletes `checklist_items` rows | WORKITEM-6 ("take bread off") | deferred |
| `reorder_checklist` | `work_item_id`, `ordered_item_ids: [int]` | sets `position` order | WORKITEM-6 | deferred |
| `clear_checked_items` | `work_item_id` | deletes all `checked` rows | WORKITEM-6 ("clear what we bought") | deferred |

### D. Calendar events (verbose verbs)

| key | params | applies to | grounds | scope |
|---|---|---|---|---|
| `create_event` | `title`, one of `{start_at,end_at}` (timed UTC) OR `{start_date,end_date}` (all-day); `description?`, `location?`, `tags?: [str]`, `participants?: [{member_id?, name}]`; links `source_update_id` | inserts `events` row | ASSIST-3; EVENT-1/2/3/5/6/7 | **v1** |
| `reschedule_event` | `event_id`, new `{start_at,end_at}` or `{start_date,end_date}` | updates only the timing fields | EVENT-1 ("move the dentist to Thursday") | v2 |
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
| `archive_work_item` | `work_item_id` | sets `archived_at` (invariant: only `done` may be archived) | GROOM-2/4 | v2 (needs GROOM) |
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

The v1 action vocabulary. Everything else in the registry is a pre-shaped slot
for v2+/deferred; add later by registering the entry (no rework of the flow).

1. **`set_due_date`** — flagship assistant field (WORKITEM-8); first real use of
   `families.timezone` for relative-date resolution.
2. **`create_event`** — the calendar bridge (ASSIST-3); exercises `source_update_id`.
3. **`complete_work_item`** — the most common lifecycle verb; composite
   (status=done + completed_at), showing why verbose verbs beat bare `set_status`.
4. **`create_work_item`** — the "this is a new thing" capture branch (WORKITEM-1).
5. **`no_action`** — reliability primitive so a small model can say "nothing."

**v1 boundaries (explicit):**
- Capture targets an **explicit work item** for item-scoped actions (`set_due_date`,
  `complete_work_item`) — assistant routing of free text to the right existing
  item is v2 (OQ-A2). `create_work_item` covers the new-item branch.
- All five actions are **propose-and-confirm** (ASSIST-2); each confirmed action
  also appends a `source=assistant` update (universal rule).
- Lightweight param checks at apply time (the registry entry lists expected
  keys); invalid/unknown actions are dropped, the raw human input is still saved
  (graceful degradation, OQ-A3).


## Open questions

- **OQ-A1** Confirm granularity: one action per card, each independently
  confirmable (per ASSIST-2). Since actions aren't persisted, the Confirm payload
  IS the action object the client sends back. Endpoint shape TBD.
- **OQ-A2** How `create_work_item` vs. `append_update` routing is decided in the
  capture flow (assistant-decided vs. UI-explicit-target) — affects whether
  capture is one endpoint or two.
- **OQ-A3** Param validation strictness for a small local model — lightweight
  checks against the registry entry's expected keys (a plain dict, not a schema
  framework); on failure, drop the action (don't fail the whole capture).
- **OQ-A4** Whether `append_update` (an assistant-composed `source=assistant`
  note as its own confirmable action) is worth having, given that every confirmed
  action already appends a `source=assistant` narration.
