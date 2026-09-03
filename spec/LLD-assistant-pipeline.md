# LLD stub — assistant capture pipeline (focus → propose)

> **Status: DESIGN IN PROGRESS — not built.** Low-level design for the task-7
> `focus()`/`propose()` functional shape. Parent HLD: DESIGN §4.1 / §4.1a.
> Records decisions from the design debate; the fake-first v1 (built) is a
> degenerate case of this. Graduates into DESIGN when implemented.

## Frame: think in functions, not a central object

`FocusedContext` is not the center — it is just the return value of `focus()`.
Reason about the pipeline as functions and their signatures; session-freeness is
then a fact about a function's *type*, not an invariant to police.

## Signatures (tagged by effect)

```
build_world_view : (Session, Member, now, tz)             -> WorldView        -- DB read; event window in tz around now
link             : (LLM, WorldView, CaptureRequest)       -> ResolvedIds      -- LLM, no DB; temporal-aware (text+tz+now)
deep_fetch       : (Session, ResolvedIds)                 -> ResolvedRecords  -- DB read; pure record pull
focus            : (LLM, Session, Member, CaptureRequest) -> FocusedContext   -- composes ↑3, then assembles
propose          : (LLM, FocusedContext)                  -> [ProposedAction] -- LLM, no DB
attach           : (FocusedContext, {name, params})       -> ProposedAction   -- pure
describe         : (name, params)                         -> Summary          -- pure
apply            : (Session, Member, ProposedAction)      -> Summary          -- DB write (separate request)
```

`focus()` body:
```
world   = build_world_view(session, member, request.now, request.tz)  # ambient state; ⊥ of the text
ids     = link(llm, world, request)                                    # temporal-aware linking → specific ids
records = deep_fetch(session, ids)                                     # pure record pull for those ids
return    FocusedContext(request, records)                             # focus() ASSEMBLES: request + records
```

## Decisions

- **Session placement (by signature).** `Session` appears only in
  `build_world_view`, `deep_fetch` (hence `focus`), and `apply`. It is **absent
  from the type of** `propose`, `link`, `attach`, `describe`. The Proposer is
  session-free *because its signature has no Session* — it cannot touch the DB.
- **`deep_fetch` is request-free; `focus()` assembles.** `deep_fetch` pulls
  records for ids and nothing more; the `CaptureRequest` (text/tz/now) is folded
  into `FocusedContext` by `focus()` in one place — not threaded through the
  fetch. (Fixes the earlier `Text`-vs-`CaptureRequest` signature mismatch: the
  request never enters `deep_fetch`.)
- **Temporal frame (`now` + `tz`) is shared ambient context.** Both
  `build_world_view` (to bound the event window in family time) and `link` (to
  resolve temporal references like "next friday's meeting" to an *existing*
  entity) receive it. Passing `tz`/`now` explicitly — rather than looking `tz` up
  from the family inside `build_world_view` — keeps those functions pure and
  seedable for tests. `link` takes the whole `CaptureRequest` since it uses all
  three fields; `build_world_view` takes `now`/`tz` only (it needs no text).
- **`WorldView` is independent of the text** (`= f(Session, Member, now, tz)`) —
  a *sibling* input to `link`, not a downstream of the text. Built by its own
  function and passed in. **Sync + uncached** for v1 (local sub-ms queries;
  caching via the change-event seam is possible later but premature).
- **New-datetime grounding stays at propose.** `link` resolves temporal refs to
  *existing* entities; grounding a *new* datetime for a create action ("friday
  3pm" → concrete UTC) happens in param-grounding, which has `tz`/`now` via
  `FocusedContext`. Both use the same temporal frame.
- **LLM is an injected effect, not a session.** `link` and `propose` take an
  `LLM` (`(system, prompt, schema) -> Json` — the shared localhost-Ollama call);
  neither takes a `Session`. The `Ollama*` classes are just these functions
  **partially applied to the LLM**: constructor captures the long-lived effect,
  the method takes per-call data — which re-derives the earlier decision (session
  is a method param, the client is a constructor field).
- **Model emits `{name, params}` only; the target is attached in code.** `attach`
  is pure: it stamps `target = (type, id)` onto the action by matching the action
  to a resolved entity in `FocusedContext` (v1: type-based, ≤1 resolved entity per
  type). The model never emits ids; ids live in `FocusedContext` solely so the
  server can attach executable targets without a lookup.
- **One `Target` representation** `(type: str, id: int | None)` end-to-end
  (`ProposedAction`, `ExecutionContext`). Kills the pre-agnostic
  `FocusedContext.work_item_id`.
- **Two engine markers, split by lifecycle:** `ReasoningContext` (read-only,
  no session; bound for the propose seam → `FocusedContext`) vs `ExecutionContext`
  (write; session/member/target; bound for the dispatch seam → today's
  `NtakeActionContext`). `WorldView` binds neither.

## Sufficiency principle (the one obligation this creates)

> `propose : (LLM, FocusedContext) -> [ProposedAction]` is a total function of
> its inputs iff `focus()`'s return value contains everything `propose`/`attach`
> read: action names (from the registry), params grounded from `tz`/`now`, and
> the resolved entity ids each proposable action could target.

Consequence: **`focus()` is coupled to the action set's *data needs*** (which
entities an action references) — not their *logic*. It must over-fetch enough
that no downstream step needs a session. Extensible path: let each `ActionSpec`
declare *what context it needs*, so `focus()` fetches by iterating the registry
rather than hard-coding (v2 nicety; v1's six actions fetch the obvious slice).

## Type taxonomy

| Type | Stage | Role | Session? |
|---|---|---|---|
| `CaptureRequest` | input | `{text, tz, now}` | — |
| `WorldView` | focus step 1→2 | broad/shallow: members, open items, windowed events | built with one |
| `ResolvedIds` | focus step 2→3 | linked work_item/event ids | — |
| `ResolvedRecords` | focus step 3 | full rows for the resolved ids | (pulled with one) |
| `FocusedContext` | focus out → propose in | `request + records`; **read-only** | none |
| `ProposedAction` | propose out | `{name, params, target?}` | none |
| `ExecutionContext` | confirm → apply | `{session, member, target}` | yes |

## Open questions

- **OQ-1 — the chain feels too long.** `request → world → link → deep_fetch →
  focus → propose → attach`. Can it collapse without losing the session-free /
  executable-by-construction properties? Candidates: have `link` return **thin
  records** so `deep_fetch` disappears (see OQ-3); or fold `attach` into
  `propose`. Revisit before implementing — do not cement the long chain.
- **OQ-2 — `WorldView` window.** How far back do events go (past week? month?);
  forward = open-ended.
- **OQ-3 — `link` output shape.** Bare `ResolvedIds`, or already-thin records? If
  `link` can return enough of each entity, `deep_fetch` collapses into it and the
  chain shortens (directly serves OQ-1). Tension: `link` is LLM-side (no session);
  returning *records* means the linking step would need DB access — so more likely
  `link` returns ids and a lightweight `deep_fetch` stays. Decide with OQ-1.
- **OQ-4 — target attachment.** Type-based, ≤1 resolved entity per type for v1;
  multi-entity / `target_ref` chaining is v2.
- **OQ-5 — JSON schema richness.** Registry `required` alone is too thin (e.g.
  `create_event`'s timed-vs-all-day **one-of**). Lean: full schema (typed params +
  one-of) owned by the `ollama/` package, **coverage-tested** against the registry
  action names — not by bloating `ActionSpec` (engine stays minimal).

## Doc debt

- `ASSISTANT_ACTIONS.md` param columns list ids as params (`work_item_id`, …) —
  pre-agnostic. Re-express as **(target, params)** to match `ProposedAction`.
