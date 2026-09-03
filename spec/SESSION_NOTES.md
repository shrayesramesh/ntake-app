# Session notes — Task 7 (Ollama) prep

> Running notes for the current session. Design decisions captured as we make
> them, before code. Source of truth for the assistant architecture remains
> DESIGN §4.1/§4.1a + PHASE4_ASSISTANT.md; this records the *deltas/choices* for
> Task 7.

## Context / snag that started this

Task 7 (the live local model) has **two** LLM-using stages, not one:

- **Stage 1 `focus()`** — generate the `FocusedContext` (currently deterministic,
  no LLM; `OllamaCaptureResolver` will make it real).
- **Stage 2 `propose()`** — `AssistantClient` (fake today; `OllamaAssistant` next).

Both will independently want to talk to Ollama, so we're organizing Task 7 code
so the **LLM transport is shared** across both stages.

## Decisions

### D1 — Rename the stage-1 seam to `CaptureResolver`

Promote the plain `focus()` function to an interface, named **`CaptureResolver`**
(not `Resolver`): it resolves a `CaptureRequest` → `FocusedContext`, and the name
won't collide with other "resolver" notions. Keep the method named **`focus()`**
for continuity with the "focus → propose" two-stage vocabulary.

- `CaptureResolver` (ABC) — `focus(request, session, member) -> FocusedContext`
- `FakeCaptureResolver` — current deterministic `focus()` body lifted in
- `OllamaCaptureResolver` — the real one (Task 7)
- `get_capture_resolver()` — factory, mirrors `get_assistant()`

Symmetric with the existing assistant seam: `CaptureRequest` →
`CaptureResolver.focus()` → `FocusedContext` → `AssistantClient.propose()`.

### D2 — Session handling: method parameter, app-scoped singleton (option A)

The `Session` is the **DB session** (SQLAlchemy unit-of-work), NOT a web/login
session. This app has no web sessions; identity is device-token → `Member` via
`current_member`. So the two per-request deps are cleanly split:
`session: Session` (DB access) and `member: Member` (who's asking).

A `Session` is short-lived, stateful, not thread-safe → its lifespan is exactly
one request. It must be per-request; it must NOT be hung on a long-lived
(config-selected) singleton.

**Chosen (A):** the resolver is a stateless, config-selected **singleton**; the
request-scoped `session` is passed **per call**.

```python
class CaptureResolver(ABC):
    @abstractmethod
    def focus(self, request: CaptureRequest, session: Session, member: Member) -> FocusedContext: ...
```

Rejected:
- **(B)** per-request `CaptureService` that holds the session — cleaner call site
  but introduces a second lifecycle concept not otherwise in this codebase, and
  splits "which implementation" (config) from "do the work".
- **(C)** session in the resolver's constructor — wrong: forces a request-scoped
  resource onto a would-be singleton (corrupts, or defeats the singleton).

(A) keeps both seams (`get_assistant`, `get_capture_resolver`) as stateless
app-scoped singletons and matches `AssistantClient.propose(ctx)` (stateless
strategy, data flows through methods). The Ollama resolver's constructor is then
reserved for long-lived transport/config (the shared `OllamaClient`); per-request
data (request/session/member) stays in the method args.

### D3 — Reusability boundary (corrects an earlier flip)

The **assistant** side is the generic/reusable one and stays generic *because*
the session never touches it: `AssistantClient.propose(ctx)` takes an opaque
`ContextT` and imports nothing app-specific (enforced by the engine boundary
test in `app.routing`). The session is deliberately kept out.

The **capture/resolver** side is the **app-coupled** seam — it's *meant* to know
the DB (`focus()` is "the ONLY capture stage that touches the database"). It
lives in `app/assistant/` (plugin), NOT `app/routing/` (engine), so taking a
`Session` costs no generic purity. The `FocusedContext` it produces is the
plain, session-free value object that crosses into the generic world.

So it's not an awkward asymmetry: **resolver = app-coupled (holds DB coupling),
assistant = generic (session-free)** — by design.

## Proposed Task-7 code layout (shared LLM transport)

```
app/assistant/ollama/
├── __init__.py     # re-exports OllamaAssistant, OllamaCaptureResolver
├── client.py       # THE shared LLM transport. One OllamaClient:
│                   #   .complete(system, context, schema) -> dict
│                   #   holds base_url, model, timeout. No prompt/domain logic.
├── assistant.py    # OllamaAssistant[FocusedContext] (stage 2): build prompt+schema,
│                   #   call client, parse -> list[ProposedAction]
├── resolver.py     # OllamaCaptureResolver (stage 1): the real focus() — resolve
│                   #   target work item, plan lookups, write genuine llm_rationale
├── prompt.py       # both stages' prompt templates
└── infra.py        # host mgmt: install/serve/pull/health (one-time, no app imports)
```

Both stage-1 and stage-2 Ollama impls are **callers** of the one `OllamaClient`
with different prompts + different JSON schemas. The schema is built FROM the
registered actions (names + params).

## Resolved config/wiring questions

- **Q1 — one switch (DECIDED):** `NTAKE_ASSISTANT` drives BOTH stages to start
  (`ollama` → resolver + assistant both go Ollama; `fake`/`off` likewise). No
  separate `NTAKE_RESOLVER` var. Matches the design doc. Revisit only if we need
  to mix stages for debugging.
- **Q2 — remove the shim (DECIDED):** delete the standalone module-level
  `focus()`; update the `/capture` endpoint and all tests that import it to go
  through `get_capture_resolver().focus(...)`. No dead seam.

## Prep-refactor plan (fake-only, no Ollama, TDD, `make check` green)

1. Add `CaptureResolver` ABC + `FakeCaptureResolver` (move existing `focus()`
   logic in) — in `capture.py`.
2. Add `get_capture_resolver()` to `factory.py` alongside `get_assistant()`
   (`ollama` branch falls back to fake for now, matching assistant factory).
3. Rewire the `/capture` endpoint in `main.py`.
4. Update imports / `__init__` exports and tests that import `focus` directly.
5. `make check` green (lint + mypy + ≥95% cov).
