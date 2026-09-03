# Next session — Ollama (task 7), the last Phase-4 item

> Handoff for resuming Phase 4. The **fake-first assistant is complete** and both
> capture stages sit behind swappable, config-selected seams. Both **prompt views
> are built** (`build_world_view`, `build_tools_view`) and the toolset is a rich
> **13 actions**. `make check` is green (257 tests, ≥95% cov). The one remaining
> Phase-4 build is the **live local model (Ollama)**, host-only. Read DESIGN §4.1
> + §4.1a and `spec/LLD-assistant-pipeline.md` first — those are the source of
> truth for the assistant architecture.

## What's built (all committed on `main`)

- **Two swappable seams, one switch.** `NTAKE_ASSISTANT` selects the backend for
  BOTH stages via `app/assistant/factory.py`:
  - Stage 1 — **`CaptureResolver`** (ABC in `app/assistant/base.py`),
    `get_capture_resolver()`. `focus(request, session, member) -> FocusedContext`.
  - Stage 2 — **`AssistantClient`** (engine contract), `get_assistant()`.
- **Backends are parallel packages.** `app/assistant/fake/` holds
  `FakeCaptureResolver` (`resolver.py`) + `FakeAssistant` (`assistant.py`);
  `app/assistant/ollama/` (task 7) will mirror it. Swap = config flip.
- **Reusable engine** (`app/routing/engine.py`): `ActionRegistry` (built from a
  flat list of specs — no imperative registration), `ActionSpec` (typed
  `params: list[Param]`, `exclusive_params`, derived `required`, `prompt_line`,
  and `execute()` which owns validate+apply), `ProposedAction`, `AssistantClient`,
  `propose_bounded`, generic `ActionContext` (PEP 695) — imports nothing
  app-specific (boundary test). No package facade: import from
  `app.routing.engine` directly.
- **Plugin** (`app/assistant/actions.py`): ntake handlers via `NtakeActionContext`.
  The toolset is now **13 actions**: `set_due_date`, `complete_work_item`,
  `start_work_item`, `move_to_on_deck`, `move_to_todo`, `reopen_work_item`,
  `assign_work_item` (whitelist-validated `member_id`), `archive_work_item`
  (done-only invariant), `add_checklist_items`, `create_event`,
  `reschedule_event` (modify-existing event), `create_work_item`, `no_action`,
  `deconflict_events`.
- **The two prompt views (built + full-string snapshot tested):**
  `build_world_view(session, family_id, now, tz)` (`app/assistant/world.py`) —
  "state of the world" (members, non-archived items, windowed events, ids inline,
  family-tz times); and `build_tools_view(registry)` (`app/assistant/tools.py`) —
  the LLM tool menu, one `spec.prompt_line` per action. Vocabulary: actions =
  execute (internal), tools = present-to-LLM.
- **Capture** is propose-only and always new (`work_item_id=None` in v1). Each
  proposal carries a registry-derived `action_summary` (ground truth) +
  `llm_rationale` (the model's account — the fake passes the focused context
  through via `render_focus`).
- **Events:** `seed_event` + fixtures + `python -m app.manage seed-events`; skinny
  calendar render (`render_calendar` + `GET /calendar/view`), live via SSE.

## Design decisions locked this session (were in SESSION_NOTES)

- **D1 — `CaptureResolver`** is the stage-1 seam name (method stays `focus()`),
  chosen over `Resolver` so it won't collide with other "resolver" notions.
- **D2 — session is a per-call method param, not a class member.** The resolver is
  a stateless, config-selected **singleton**; the request-scoped DB `Session`
  flows into `focus()` per call. Rejected: session in the constructor (forces a
  request-scoped resource onto a would-be singleton) and a per-request
  `CaptureService` holder (adds a lifecycle concept not otherwise present).
  "Session" here = the SQLAlchemy DB session; this app has no web/login sessions
  (identity is device-token → `Member`).
- **D3 — reusability boundary.** The **assistant** (stage 2) is the generic piece
  and stays session-free (engine boundary test enforces it). The
  **capture/resolver** (stage 1) is the app-coupled seam — it's *meant* to touch
  the DB — and lives in `app/assistant/`, not the engine, so taking a `Session`
  costs no generic purity.
- **Q1 — one switch.** `NTAKE_ASSISTANT` drives both stages to start (no separate
  `NTAKE_RESOLVER`). Revisit only if we need to mix stages for debugging.
- **Q2 — no shim.** The old module-level `focus()` was removed; callers go through
  `get_capture_resolver().focus(...)`.

## FakeAssistant trigger vocabulary (for smoke/manual testing)

Timing needs a **weekday** word. New capture: **event word**
(appointment/event/meeting/visit) **+ weekday** → `create_event` only; else →
`create_work_item`. Existing item: weekday → `set_due_date` (+ linked
`create_event` if event-ish); **done word** → `complete_work_item`. Two events in
`calendar_window` sharing a start → `deconflict_events` (moves the later-created
one +1 day). Full table: `app/assistant/fake/assistant.py` docstring.

---

## Task 7 — the Ollama backend (host-only, LAST)

The only remaining Phase-4 build. **Live model runs on the host** (like the
Tailscale manual step); develop against the fakes, human runs the live test.
Ollama is **not installed on this dev Mac** — install + `ollama pull llama3.1:8b`
is a host step. Proposed layout, mirroring `fake/`:

```
app/assistant/ollama/
├── client.py     # OllamaClient: HTTP wrapper (httpx, already a dep), format=schema
│                 #   JSON call; holds base_url/model/timeout. Schema built FROM
│                 #   the registered actions (names + params). No prompt/domain logic.
├── assistant.py  # OllamaAssistant[FocusedContext] (stage 2): build prompt+schema,
│                 #   call client, parse -> [ProposedAction]
├── resolver.py   # OllamaCaptureResolver (stage 1): the real focus() — resolve a
│                 #   target work item (work_item_id becomes non-None), plan lookups,
│                 #   write a genuine llm_rationale (replacing the fake pass-through)
├── prompt.py     # system + context prompt templates for both stages
└── infra.py      # host mgmt: health/pull (install stays a documented human step)
```

- **Config:** `NTAKE_ASSISTANT=ollama`, `NTAKE_ASSISTANT_MODEL` (default
  `llama3.1:8b`), `NTAKE_OLLAMA_URL` (default `http://localhost:11434`),
  `NTAKE_ASSISTANT_TIMEOUT` (default 4.0). Wire the `ollama` branch in both
  factory functions (currently both fall back to the fake).
- **Prompt:** system (role + available actions/params, "propose only from these;
  use no_action; dates in family tz") + context (now, tz, item log, calendar
  window) + raw text. Non-thinking model → no `<think>` stripping.
- **Build order (each a sub-checkpoint, `make check` green, TDD vs. a stubbed
  httpx — no live model needed):** (1) the JSON `format` **schema generator** from
  the specs (`ActionSpec.params`/`exclusive_params` are already there — see the
  resolved decision below); (2) `client.py` (`OllamaClient`); (3) `OllamaAssistant`
  (assemble prompt from `build_world_view` + `build_tools_view` + raw text, call
  client, parse → `[ProposedAction]`); (4) `OllamaCaptureResolver`; (5) `infra.py`
  + a `manage ollama` health/pull subcommand.

### Resolved: action param schema (was OQ-5 → option B)

The param contract lives **on `ActionSpec`** as `list[Param]`
(`Param(name, datatype, required)`) + `exclusive_params` (mutually-exclusive
groups, e.g. create_event's timed-vs-all-day). `required` derives from `params`;
`prompt_line` renders each action for the tool menu; the JSON schema generator
(step 1 above) reads the same specs. Output shape is the uniform option-A
`{actions: [{name, params}]}`, with params validated against each spec **after**
emission (graceful-degrade). See `spec/LLD-assistant-pipeline.md` for the full
functional design + open questions (incl. OQ-1 pipeline shape / the 2-call goal).

## Polish / gaps (lower priority)

- **Integration coverage (real-stack) gaps** worth closing in the smoke script:
  (1) confirm a **standalone `create_event`** over real HTTP → shows in
  `/calendar/view`, no work item; (2) **`deconflict_events`** end-to-end;
  (3) SSE-triggered calendar refresh.
- **Double-confirm semantics:** proposals aren't persisted, so confirming twice
  re-applies (deconflict → +2 days). Accepted for v1; document if it surfaces.
- **GROOM board UI** — the board is read-only today (no archive/unarchive UI).
  Note the *assistant* `archive_work_item` action IS built (done-only invariant);
  it's the board's manual grooming UI that's still Phase-5.
- **`item_log`** is `[]` until a target is resolved (arrives with OllamaCaptureResolver).
- **Alembic** migration wiring still deferred (tests/app use `create_all`).

## House rules (unchanged)

TDD; `make check` (lint + mypy + ≥95% cov) before any task is done. `make smoke`
for the host integration smoke; `--serve` keeps the server up + prints a token
for a browser check. Do NOT do Tailscale/device/deploy steps (human-only). Do NOT
`git push`.
