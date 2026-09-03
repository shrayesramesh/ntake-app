# Next session — event scaffolding + reusable action-routing package

> Handoff for resuming Phase 4. Everything through **task 6 is committed**
> (`origin/main`); backend flow (capture → propose → confirm → apply) + inline
> Confirm/Dismiss cards are done and browser-verified. `make check`: 110 tests,
> 98% coverage. `make smoke`: 7/7. Work TDD; `make check` (≥95% cov) per task.

## Why this fork exists

Events are **underdeveloped**: the `Event` model + `GET /events` (JSON) exist, but
there is **no way to create events for testing** (only via the assistant
`create_event` action), **no UI rendering** of events, and
`CaptureContext.calendar_window` is declared but **unused/unpopulated**. Rather
than punt calendar context to "later", scaffold events end-to-end so
context-aware actions are real and testable.

## Build order (respects dependencies)

```
9 (event seed) → 11 (calendar render) → 8 (two summaries)
      → 12 (generalize target) → 10 (conflict/deconflict action) → 7 (Ollama)
```
- **9 before 10/11:** need to create events before rendering them or acting on them.
- **12 before 10:** a deconflict action targets *events*, so the target must be
  generalized (work item OR event) first.
- **7 last:** OllamaAssistant needs `calendar_window` populated (done in 10) to be
  worth wiring; it's host-only (live-test like Tailscale 1f).

---

## Task 9 — Event seeding (do first)

A way to create events directly, without going through the assistant.
- A small seed helper (e.g. `seed_event(session, family_id, ...)`), a pytest
  fixture (`event_factory` / `seeded_events`), **and** a seed path usable from the
  host smoke (so the calendar can be populated for manual testing).
- Consider a dev-only `POST /events` create endpoint OR extend the manage CLI
  (`python -m app.manage seed-events`). Prefer whatever keeps prod surface small;
  a test fixture + a CLI/seed script is enough. (Direct human event CRUD in the
  UI is NOT required — events arrive via the assistant or seed.)
- TDD: seeding creates timed + all-day events; they show in `GET /events`.

## Task 11 — Skinny calendar render

Show event cards in the UI so events are visible and the wiring is understood.
- A render fragment (grow `app/web.py`: a `render_calendar(events)` like
  `render_board`) + a `GET /calendar/view` HTML fragment (auth-protected), OR add
  an events section to the existing board page.
- Agenda/list is fine (no grid needed). Escape HTML. Tag chips optional.
- TDD the fragment (renders event titles/times, escapes, requires auth). Wire it
  into the shell + SSE reload so it live-updates like the board.

## Task 8 — Two summaries (2a; small refactor)

Split the single `ProposedAction.summary` into two distinct concepts:
- **`action_summary`** — deterministic, **registry-derived**: what the action WILL
  actually do, generated from params. Add a per-action `describe(params) -> str`
  to each `ActionSpec` in `app/assistant/actions.py`. This is ground truth.
- **`llm_rationale`** — the **model's** narration / why it proposed this (may be
  wrong; absent for the fake or set to a canned string). Passed through generically.
- Cards show both: the action truth prominently, the rationale as secondary
  context. Update `ProposedAction`, `ProposalRead`, `_propose_bounded`, the
  registry entries, and `web.py` card render. TDD.

## Task 12 — Generalize the action target (2b)

An action can target a **work item OR an event OR neither** — don't force
everything through a work item.
- Add `target_type: "work_item" | "event" | None` alongside `target_id` on
  `ProposedAction` / `ProposalRead` / `ConfirmAction`.
- The universal "append a `source=assistant` work_item_update" rule becomes
  **conditional**: only when the action targets a work item. Event-only actions
  (reschedule/deconflict/cancel) do NOT append a work-item update — there's no
  work item, and events aren't part of the labor log (WORKITEM-3). A standalone
  event edit just mutates the event.
- Update `apply_action` dispatch + the handlers + `/actions/confirm`. Keep the key
  count small — this generalizes the *target*, not the action vocabulary.
- TDD: a work-item action still logs; an event-target action mutates the event and
  does NOT append a work-item update.

## Task 10 — MVP context-aware event action (deconflict)

The placeholder that exercises calendar context end-to-end:
- Populate `CaptureContext.calendar_window` in `/capture` from real events near the
  capture (a compact list/summaries).
- Add a `deconflict_events` action (targets events, per task 12): given two events
  at the same time, "move one (pick deterministically for the placeholder — e.g.
  the later-created) to the next day". This is a stand-in to prove context flows
  in → action out → apply, NOT smart scheduling.
- FakeAssistant: when the context shows two overlapping events, propose
  `deconflict_events`. TDD: seed two conflicting events (task 9) → capture → the
  fake proposes deconflict → confirm → one event moves to next day.

## Task 7 — OllamaAssistant (host-only, LAST)

`format`-constrained JSON to Qwen/llama; prompt with tz/now + item log + calendar
window; parse to actions. Wired here (config `NTAKE_ASSISTANT=ollama`), but the
live test runs on the host with Ollama (`llama3.1:8b` default) — like the
Tailscale 1f manual step. Model is a config value; A/B via `NTAKE_ASSISTANT_MODEL`.

---

## Cross-cutting: extract the action-routing engine into its own mini-package

> **Do this as its own focused refactor** — ideally after task 12 (which reshapes
> the target), OR interleaved if it clarifies the target work. It touches tasks
> 2/4/5/8/12 code. Keep `make check` green throughout; TDD the engine in isolation.

### Goal
Separate the **domain-agnostic propose/route/confirm ENGINE** from the
**ntake-specific PLUGIN** (the actions + endpoints), so the engine is reusable
across projects. **Package-shape now, not a separately published package** —
structure it as a self-contained sub-package that a *directory move* could later
turn into an installable package. Only publish separately if a concrete second
consumer appears.

### The split

**Engine (reusable — MUST import nothing app-specific: no models, no Session, no
Member, no FastAPI):** e.g. `app/routing/` (or `app/propose_confirm/`)
- `AssistantClient`, `ProposedAction`, a **generic** `CaptureContext` (just the
  fields the engine needs; app-specific fields move to the plugin or a subclass).
- A generic **`ActionRegistry`**: `register(name, *, required, describe, handler,
  needs_target=...)`; `dispatch(name, params, context) -> result` that validates
  and calls the handler. `context` is an **opaque object the engine passes
  through** — the engine never inspects it.
- A uniform `ActionError`.
- The bounded-timeout + graceful-degrade wrapper (`propose_bounded`).
- The `{actions:[{name,params}]}` contract + an Ollama `format`-constrained client
  that builds its JSON schema **from the registered actions** (names + params).
- Engine tests use a **fake handler + fake opaque context** — zero ORM, zero app
  imports. This is what enforces the boundary.

**Plugin (ntake-specific — imports the engine):** stays in `app/assistant/`
- Registers ntake's actions into an engine `ActionRegistry`: each handler receives
  the opaque `context` the app injects — here `(session, member, target_id/…)` —
  and does the ORM mutation + the conditional `source=assistant` append.
- `describe(params)` per action (the `action_summary` from task 8) lives here.
- The `/capture` and `/actions/confirm` endpoints build the app context and call
  the engine.
- `FakeAssistant` (ntake keyword canned proposals) stays here.

### Boundary rule (enforce with a test)
Add a test that imports the engine package and asserts it does **not** transitively
import `app.models` / `sqlalchemy` / `fastapi` (e.g. inspect `sys.modules` after a
fresh import, or a simple import-linter-style check). This guarantees
extractability.

### Migration steps (suggested)
1. Create the engine package; move `ActionSpec`→generic registry, `apply_action`
   →`dispatch`, `ActionError`, `_require`, `propose_bounded`, the `AssistantClient`
   /`ProposedAction`/generic `CaptureContext`.
2. Leave the ntake handlers (`_apply_*`, `describe`) + `FakeAssistant` in
   `app/assistant/`, registering into an engine registry instance at import.
3. Repoint `main.py` (`/capture`, `/actions/confirm`) at the engine dispatch,
   passing the app context object.
4. Add the boundary test. Keep every existing test green (they exercise behavior,
   which shouldn't change).
5. Update PLAN's "reusable propose-confirm engine" note to "done / where it lives".

### Watch-outs
- Don't let the generic `CaptureContext` keep `work_item_id`/`calendar_window`
  (app domain) — either subclass it in the plugin or pass those inside the opaque
  context.
- Keep the action **vocabulary** unchanged; this is a structural move, not a
  behavior change.
- The two-summary (task 8) and typed-target (task 12) changes should land in the
  engine's generic shape (`action_summary`/`llm_rationale`, `target_type`) so the
  engine is right, not just moved.
