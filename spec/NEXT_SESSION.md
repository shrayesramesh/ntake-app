# Next session — Ollama (task 7) + polish

> Handoff for resuming Phase 4. The **fake-first assistant is complete**: capture
> → focus → propose → confirm works end to end over a reusable engine, browser-
> verified via `make smoke --serve`. `make check` is green (~200 tests, ≥95%
> cov). The remaining Phase-4 work is the **live local model (Ollama)**, which is
> host-only. Read DESIGN §4.1 + §4.1a first — that's the source of truth for the
> assistant architecture.

## What's built (all committed on `main`)

- **Events:** `seed_event` helper + `event_factory`/`seeded_events` fixtures +
  `python -m app.manage seed-events` (no human event-CRUD UI; events arrive via
  the assistant or seed). Skinny calendar render (`render_calendar` +
  `GET /calendar/view`), live via SSE like the board.
- **Assistant (two-stage, fake-first):**
  - **Stage 1 `focus()`** (`app/assistant/capture.py`): `CaptureRequest` → DB
    lookups → `FocusedContext` (id-bearing `calendar_window`). v1 resolves **no**
    target from text (`work_item_id=None`; every capture is new).
  - **Stage 2 `propose()`**: `FakeAssistant` over the engine.
  - **Reusable engine** (`app/routing/engine.py`): `ActionRegistry`/`ActionSpec`,
    `ProposedAction`, `AssistantClient`, `propose_bounded`, generic
    `ActionContext` (PEP 695) — imports nothing app-specific (boundary test).
  - **Plugin** (`app/assistant/actions.py`): ntake handlers register into the
    engine via `NtakeActionContext`. v1 actions: `set_due_date`, `create_event`
    (standalone OR work-item-linked), `complete_work_item`, `create_work_item`,
    `deconflict_events`, `no_action`.
  - **Proposals:** propose-only capture (nothing saved until Confirm); each
    proposal fully defines its operation (no dangling target); carries a
    registry-derived `action_summary` (ground truth) + `llm_rationale` (the
    model's account — fake passes the focused context through via `render_focus`);
    `target_type` (work_item|event|None) drives the conditional `source=assistant`
    log rule; batch-local `proposal_id`; `target_ref` reserved for v2 chaining.

## FakeAssistant trigger vocabulary (for smoke/manual testing)

Timing needs a **weekday** word. New capture: **event word**
(appointment/event/meeting/visit) **+ weekday** → `create_event` only; else →
`create_work_item`. Existing item: weekday → `set_due_date` (+ linked
`create_event` if event-ish); **done word** → `complete_work_item`. Two events in
`calendar_window` sharing a start → `deconflict_events` (moves the later-created
one +1 day). Full table: `app/assistant/fake.py` docstring.

---

## Task 7 — OllamaAssistant + OllamaResolver (host-only, LAST)

The only remaining Phase-4 build. **Live model runs on the host** (like the
Tailscale manual step); develop against the fakes, human runs the live test.

- **`OllamaAssistant[FocusedContext]`** (stage 2): `format`-constrained JSON call
  to Qwen/llama; the engine's Ollama client builds its JSON schema **from the
  registered actions** (names + params). Parse to `ProposedAction`s. Config:
  `NTAKE_ASSISTANT=ollama`, `NTAKE_ASSISTANT_MODEL` (default `llama3.1:8b`),
  `NTAKE_OLLAMA_URL`, `NTAKE_ASSISTANT_TIMEOUT`.
- **`OllamaResolver`** (stage 1): the real `focus()` — read the text to resolve a
  target work item (`work_item_id` becomes non-None) and plan lookups; write a
  genuine "what I understood" into `llm_rationale` (replacing the fake's
  pass-through). Promote `focus()` to a `Resolver` interface + `get_resolver()`
  factory (mirror `get_assistant`) when this lands.
- **Prompt:** system (role + available actions/params, "propose only from these;
  use no_action; dates in family tz") + context (now, tz, item log, calendar
  window) + raw text. Non-thinking model → no `<think>` stripping.

## Polish / gaps (lower priority)

- **Integration coverage (real-stack) gaps** worth closing in the smoke script:
  (1) confirm a **standalone `create_event`** over real HTTP → shows in
  `/calendar/view`, no work item; (2) **`deconflict_events`** end-to-end (seed 2
  conflicts → capture → confirm → one moves); (3) SSE-triggered calendar refresh.
- **Double-confirm semantics:** proposals aren't persisted, so confirming twice
  re-applies (deconflict → +2 days). Accepted for v1 (human action); document if
  it surfaces.
- **GROOM actions** (`archive_work_item`, …) — v2; board is read-only today.
- **`item_log`** is `[]` until a target is resolved (arrives with OllamaResolver).
- **Alembic** migration wiring still deferred (tests/app use `create_all`).

## House rules (unchanged)

TDD; `make check` (lint + mypy + ≥95% cov) before any task is done. `make smoke`
for the host integration smoke; `--serve` keeps the server up + prints a token
for a browser check. Do NOT do Tailscale/device/deploy steps (human-only). Do NOT
`git push`.
