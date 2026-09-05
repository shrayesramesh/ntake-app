# LLD — assistant capture pipeline (link → propose, two LLM calls)

> **Status: DESIGN — not built.** Low-level design for the task-7 capture
> pipeline. Parent HLD: DESIGN §4.1 / §4.1a. Records the design-debate decisions;
> the current fake-first v1 (built) is a degenerate case (deterministic `focus()`,
> no linking LLM). Graduates into DESIGN when implemented.

## The v1 pipeline in one picture (OQ-1, resolved: two LLM calls)

```
CALL 1 — LINK (LLM):  shallow WorldView (id-bearing menu) + the note
                       → ResolvedIds  (which [w#]/[e#]/[m#] the note is about —
                         work items, events, AND members, family-whitelisted)
        ↓ deterministic
   DEEP FETCH:         full records for ONLY those ids — a work item's entire
                       work_item_updates history, the event's full record, …
        ↓
CALL 2 — PROPOSE (LLM): TOOLS VIEW + the note + the deep/narrow context
                        → [ProposedAction]   (id-free; target attached in code)
```

Deliberate token trade: **broad-but-shallow to find the targets, then
narrow-but-deep to reason.** Full details of the flow + rationale are under
"Open questions → OQ-1".

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
  `LLM` (`(system, prompt, schema) -> Json` — the shared localhost LLM call, an
  OpenAI-style HTTP round trip; llamafile is the reference runtime); neither takes
  a `Session`. The `LocalLlm*` classes are just these functions
  **partially applied to the LLM**: constructor captures the long-lived effect,
  the method takes per-call data — which re-derives the earlier decision (session
  is a method param, the client is a constructor field).
- **Model emits `{name, params}` only; the target is attached in code.** `attach`
  is pure: it stamps `target = (type, id)` onto the action by matching the action
  to a resolved entity in `FocusedContext` (v1: type-based, ≤1 resolved entity per
  type). The model never emits ids; ids live in `FocusedContext` solely so the
  server can attach executable targets without a lookup.
- **One `Target` representation** `(type: str, id: int | None)` end-to-end
  (`ProposedAction`, `ExecutionContext`). The pre-agnostic single
  `FocusedContext.work_item_id` is retired (A2 reshape): `FocusedContext` now
  carries `resolved_work_item_ids` / `resolved_event_ids`, and `attach` reads the
  `primary_work_item_id` / `primary_event_id` accessors (first resolved id, ≤1 per
  type in v1).
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

- **OQ-1 — pipeline shape. RESOLVED: two LLM calls (link → deep_fetch → propose).**
  The v1 pipeline is `build_world_view → link(LLM) → deep_fetch → propose(LLM)`:
  1. **Link (LLM call 1):** shallow `WorldView` (the id-bearing menu of members /
     open items / windowed events) + the note → the **relevant identities**
     (`ResolvedIds`: which `[w#]`/`[e#]` the note is about).
  2. **Deep fetch (deterministic):** for *only* those ids, pull the **full
     records** — a work item's entire `work_item_updates` history, the event's
     full record, etc.
  3. **Propose (LLM call 2):** `TOOLS VIEW` + the note + the **deep, narrow**
     context (not the whole world) → `[ProposedAction]`.

  Rationale (the deliberate token trade): **broad-but-shallow to find the
  targets, then narrow-but-deep to reason.** Full histories for every entity in
  call 1 would be wasteful (most are irrelevant); only the shallow world in call 2
  would starve the reasoning. This also resolves target attachment cleanly — call
  1 produces the ids, so by call 2 the target is already resolved server-side and
  the propose model still emits id-free `{name, params}` (no id-guessing in the
  reasoning call). This is the richer product: "the plumber is coming friday"
  resolves to the real plumber item + its history. **Cost accepted for v1:** two
  sequential local-model calls in the request path (see DESIGN §4.1's synchronous-latency limitation), and `focus()` is NOT deterministic
  (`LocalLlmCaptureResolver` is a real LLM component in v1). This **supersedes** the
  earlier "deterministic v1 focus / one call" lean.
- **OQ-2 — `WorldView` window.** Built as `window_days=7` (past window, forward
  open-ended), a parameter tunable later.
- **OQ-3 — `link` output shape. RESOLVED: bare `ResolvedIds`.** `link` is LLM-side
  (no session), so it returns ids, not records; `deep_fetch` (which has the
  session) pulls the full records. Keeping them separate is what enables the
  shallow-then-deep trade in OQ-1 — `link` sees only the shallow world, deep_fetch
  materializes only the linked ids.
- **OQ-4 — target attachment.** Type-based, ≤1 resolved entity per type for v1;
  multi-entity / `target_ref` chaining is v2.
- **OQ-6 — deep-context size + member footprint.** `deep_fetch` sends a work
  item's **full** `work_item_updates` log in v1 (family scale → short logs;
  uncapped is fine; cap to last-N only if a log ever bloats the prompt). The deep
  context **always includes the capturing member's footprint** — their assigned
  work items **and the events they participate in** (their `member_id` in the
  event's `participants` list) — AND, since member linking landed, the same
  footprint for **each member the LINK step resolves** (people the note names, e.g.
  "drive Sam to practice"), unioned with the note-linked entities (deduped), with a
  member header (`NOTE FROM:` the author + `ALSO ABOUT:` any linked others) so
  PROPOSE can reason about each named person's load (the labor-visibility core).
  Built in `app/assistant/local_llm/link.py` (`parse_ids` → 3-tuple incl.
  `member_ids`) and `app/assistant/context/deep.py` (`resolve_ids` family-
  whitelist + `deep_context`). The `Event.participants` column (JSON list of
  `{member_id?, name}`, EVENT-5) was added for this; `create_event` writes it and
  `seed_event` accepts it. *(Was deferred as QQ-6 pending the participants column —
  now resolved.)*
- **OQ-5 — action param schema. RESOLVED (see "Resolved: action param schema"
  below).** Typed params live **on `ActionSpec`** as `list[Param]` (option B):
  the engine carries them as plain data (not required-only, not a schema
  framework), and both validation and the model catalog/prompt derive from them.

## Resolved: action param schema (OQ-5 → option B, typed params on the spec)

The model must cite an action **name** + its **params**. Deriving the param
contract needs types + optionality + a cross-param one-of — more than the
current `required: list[str]`. Decision: carry that **on `ActionSpec` as
`list[Param]`** (single source; validation *and* the model catalog/prompt both
derive from it), rather than a second catalog in the local_llm package.

Authoring style chosen: **lightest engine, verbose authoring** — plain `Param`
dataclass, no stringly-typed `!` convention, no signature introspection.

```python
class DataType(Enum):
    # closed param-type vocabulary; each member carries BOTH projections:
    # value = (human_token, json_schema)
    STRING        = ("string",        {"type": "string"})
    DATETIME      = ("datetime",      {"type": "string", "format": "date-time"})
    DATE          = ("date",          {"type": "string", "format": "date"})
    INTEGER       = ("integer",       {"type": "integer"})
    ARRAY_STRING  = ("array<string>", {"type": "array", "items": {"type": "string"}})
    ARRAY_INTEGER = ("array<integer>",{"type": "array", "items": {"type": "integer"}})
    OBJECT        = ("object",        {"type": "object"})

    @property
    def human_token(self) -> str: return self.value[0]   # tools VIEW render
    @property
    def json_schema(self) -> dict: return self.value[1]  # tools SCHEMA fragment


@dataclass(frozen=True)
class Param:
    name: str
    datatype: DataType   # a closed-enum member; carries human_token + json_schema
    required: bool = False


@dataclass(frozen=True)
class ActionSpec[ContextT: ActionContext]:
    name: str                                            # identifier AND registry key
    description: str = ""                                # human sentence for the model
    params: list[Param] = field(default_factory=list)
    exclusive_params: list[list[str]] = field(default_factory=list)  # groups; supply exactly one group (param names)
    target_type: str | None = None      # "work_item" | "event" | None; opaque str to the engine, app supplies the TargetType StrEnum (data model). Default None = targets nothing (safe/inert).
    logs: bool = True
    apply: Handler[ContextT] = None       # type: ignore[assignment]
    describe: DescribeFn = None            # type: ignore[assignment]

    @property
    def needs_target(self) -> bool:        # derived — target_type is the single source
        return self.target_type is not None

    @property
    def required(self) -> list[str]:       # derived — single source is params
        return [p.name for p in self.params if p.required]

    @property
    def prompt_line(self) -> str:          # renders ITSELF as the LLM menu line
        parts = [f"{p.name}: {p.datatype.human_token}{'' if p.required else '?'}" for p in self.params]
        params_txt = ", ".join(parts) if parts else "(no params)"
        line = f"- {self.name}: {self.description} — params: {params_txt}"
        if self.exclusive_params:
            groups = " OR ".join(
                "{" + ", ".join(g) + "}" for g in self.exclusive_params
            )
            line += f"  (exactly one of: {groups})"
        return line
```

Decisions locked:

- **`DataType` is a closed enum carrying BOTH projections.** Each member holds
  `(human_token, json_schema)`, so the tools *view* (`human_token`) and the tools
  *schema* (`json_schema`) both derive from the one definition — adding/changing a
  type is a single edit that cannot desync the two renders. `params` (built from
  these) is the single source of truth for both.
- **`datatype`, not `type`** — avoids shadowing the builtin. The literal
  JSON-Schema keyword `"type"` lives ONLY inside each member's `json_schema`
  fragment; the fragment is passive data the engine stores but never acts on, and
  the JSON-Schema *assembly* (envelope, per-action `oneOf`) still happens only in
  the local_llm package (`build_tools_schema`). So the engine stays
  domain-agnostic (the boundary test still holds) while the fragment lives with
  its vocabulary.
- **`name` on the spec IS the registry key.** `register(spec)` uses `spec.name`
  (drop the separate `name` arg to `register`). No duplication; `prompt_line`
  needs no argument because `self.name` is present.
- **`description` kept** (distinct from `name`): the human sentence materially
  helps a small model; cheap to author.
- **`required` is a derived property** (single source = `params`); `dispatch` /
  `require_params` are unchanged (they still read `spec.required`).
- **`exclusive_params` is separate** (mutually-exclusive param *groups*, supply
  exactly one group; references param names); the engine ignores it — the local_llm
  schema generator turns it into JSON-Schema `oneOf`. Named for the domain
  property, not JSON Schema's keyword (same reasoning as `datatype` vs `type`).
- **`prompt_line` lives on `ActionSpec`** (data renders itself). It formats only
  its own generic fields — imports nothing app/LLM-specific, so the engine
  boundary test still holds.

Example authored actions (v1):

```python
ActionSpec(
    name="set_due_date",
    description="Set a work item's due date.",
    params=[Param("due_at", DataType.DATETIME, required=True)],
    apply=_apply_set_due_date, describe=_describe_set_due_date,
)

ActionSpec(
    name="create_event",
    description="Create a calendar event (timed OR all-day).",
    params=[
        Param("title", DataType.STRING, required=True),
        Param("description", DataType.STRING),
        Param("location", DataType.STRING),
        Param("start_at", DataType.DATETIME),
        Param("end_at", DataType.DATETIME),
        Param("start_date", DataType.DATE),
        Param("end_date", DataType.DATE),
    ],
    exclusive_params=[["start_at", "end_at"], ["start_date", "end_date"]],
    apply=_apply_create_event, describe=_describe_create_event,
)
```

Entity-target params (`work_item_id`, `event_id`) are NOT params — they are the
server-attached `target` (opaque to the model). v1 type vocabulary actually
needed: `DataType.STRING`, `DataType.DATETIME`, `DataType.DATE`, plus the one-of.
(`INTEGER`, `ARRAY_STRING`/`ARRAY_INTEGER`, `OBJECT` are pre-shaped for v2 actions
— assign, checklist, participants.)

**Vocabulary — "actions" vs "tools".** "Actions" are what we *execute*
(`ActionSpec`/`ActionRegistry`/`ProposedAction`/`apply_action` — unchanged
internal domain). "Tools" are how those same actions are *presented to the LLM*.
An action becomes a *tool* only at the model boundary; a `ProposedAction` coming
back is a *tool call* we translate into an action to execute. So the model-facing
renderer + JSON schema live in the local_llm package under the "tools" name, while
the engine keeps the "action" vocabulary.

**Catalog / prompt** = the registry loop the model reads, exposed at the LLM
boundary as **`build_tools_view(registry) -> str`** (the parallel of
`build_world_view`): `"\n".join(spec.prompt_line for spec in registry.all())`.
The JSON `format` schema (option A output shape) is generated from the same
specs — a uniform `{actions: [{name: enum[...], params: object}]}` — with params
validated against each spec's `params`/`exclusive_params` **after** emission
(graceful-degrade: drop invalid).

**Implementation order (engine-first, TDD, `make check` green each step):**
1. Add `Param`; swap `ActionSpec.required` → `params: list[Param]` + derived
   `required`; add `name`/`description`/`exclusive_params`/`prompt_line`;
   `register(spec)`
   keys off `spec.name`. Prove `dispatch`/validation unchanged.
2. Migrate the six v1 specs to `params=[Param(...)]`.
3. Catalog/prompt builder + the JSON-schema generator (local_llm package).

## Doc debt

- `ASSISTANT_ACTIONS.md` param columns list ids as params (`work_item_id`, …) —
  pre-agnostic. Re-express as **(target, params)** to match `ProposedAction`.
