# Family Calendar + Work Items on AWS — Low-Level Design (LLD)

> Detailed design for the from-scratch AWS rebuild. Architecture is in
> [`AWS_HLD.md`](AWS_HLD.md); the phased build is in [`AWS_PLAN.md`](AWS_PLAN.md).
> This document fills in the concrete contracts the HLD deferred: single-table
> keys/GSIs, the repository method set, the Anthropic-API seams + schema
> translation, the WebSocket wiring, the Lambda authorizer + minting, assistant
> logging, the CDK
> stack layout, the test strategy per tier, and the frontend client.
>
> **Region:** `us-east-1`. **Account:** `111037110464`.
> **Conventions:** all timestamps stored **UTC** (ISO-8601, `Z`), set
> **server-side** in the handler (`datetime.now(UTC)`); ids are **ULID** strings
> minted **server/Lambda-side at write time** (the client supplies neither ids nor
> stored timestamps — the request's `now` is prompt context only, §3.1);
> `family_id` is the partition dimension; every access pattern below is a single
> DynamoDB operation unless noted.

---

## 1. DynamoDB single-table schema

### 1.1 Table + keys
One table, `ntake-<stage>` (e.g. `ntake-dev`, `ntake-prod`). On-demand billing.

- **PK** (partition key): a type-prefixed string that groups an item under its
  family or its parent entity.
- **SK** (sort key): a type-prefixed string ordering items within a partition.
- **Two GSIs:** `GSI1` (board), `GSI2` (calendar) — sparse, keyed only on the
  items that participate.

Prefix convention (readability + collision-free): `FAM#<ulid>`, `WI#<ulid>`,
`EV#<ulid>`, `MEM#<ulid>`, `TOK#<hash>`, `CONN#<connId>`.

### 1.2 Item types

**Family** — one per household.
- PK `FAM#<familyId>` · SK `#META`
- attrs: `name`, `timezone` (IANA, e.g. `America/New_York`), `tag_colors` (map),
  `created_at`

**Member**
- PK `FAM#<familyId>` · SK `MEM#<memberId>`
- attrs: `display_name`, `role` (`adult|child`), `phone_number?`, `created_at`
- (Co-located under the family partition → "list members of a family" is a Query
  on `FAM#<familyId>` with SK `begins_with(MEM#)`.)

**Device token**
- PK `TOK#<token_hash>` · SK `#META`  *(looked up by hash — see §5)*
- attrs: `family_id`, `member_id`, `label`, `created_at`, `revoked_at?`
- A **GSI is not needed**: the authorizer looks up by hash, which is the PK.

**Work item** — the co-located aggregate (HLD §6). One item carries the item
fields **plus** nested recent log + checklist.
- PK `FAM#<familyId>` · SK `WI#<workItemId>`
- attrs: `title`, `description?`, `status` (`todo|on_deck|doing|done`),
  `position` (int), `assigned_to?` (memberId), `due_at?`, `tags` (list),
  `created_at`, `updated_at`, `completed_at?`, `archived_at?`
- **nested `updates`**: ordered list of `{update_id, author_id, source
  (human|assistant), body, created_at}` — the recent log (append via
  `list_append`).
- **nested `checklist`**: ordered list of `{text, checked, position}`.
- **nested `log_segments?`**: reserved list of `{s3_key, from_ts, to_ts}` — the
  **S3-spill pointer slot** (empty in v1; see §1.5).
- **GSI1 (board):** `GSI1PK = FAM#<familyId>#BOARD`, `GSI1SK =
  STATUS#<status>#POS#<zero-padded-position>` — **written only when
  `archived_at` is null** (sparse). Archiving removes the GSI1 keys → the item
  drops out of the board index.

**Event** — flat single item (HLD §6).
- PK `FAM#<familyId>` · SK `EV#<eventId>`
- attrs: `title`, `description?`, `location?`, `all_day` (bool),
  `start_at?`/`end_at?` (UTC, timed), `start_date?`/`end_date?` (date, all-day),
  `participants` (list of names), `tags` (list), `created_at`, `updated_at`
- **denormalized provenance** (HLD §6, agreed): `provenance?` =
  `{work_item_id, member_id, member_name, note_snippet, at}` written at confirm
  time; `source_update_id?` is **also** set — the handler, when creating from a
  work item, appends an assistant log entry and stores its id here. Both coexist:
  the `provenance` snippet makes the event self-describing (survives source
  deletion), `source_update_id` is the precise backlink, **resolve-on-read** (a
  deleted source just blanks the backlink). A standalone-created event (no
  work-item target) has neither.
- **Two creation paths** (match the handlers): **standalone** (`put_event`, one
  `Put`) vs. **co-created from a work-item update** (`create_event_from_update`,
  a `TransactWriteItems` of the event `Put` + the work-item log `UpdateItem`).
- **GSI2 (calendar):** `GSI2PK = FAM#<familyId>#CAL`, `GSI2SK =
  TS#<sort_ts>#EV#<eventId>` where `sort_ts` = the UTC instant for timed events,
  the family-midnight UTC instant for all-day (one sortable key; both stored
  fields kept for rendering). Also set on **due-dated work items** (the
  calendar/due-date bridge) with `TS#<due_at>#WI#<id>` so the calendar Query
  returns events + due items in one pass. **GSI2 lifecycle asymmetry:** an **event**
  can be deleted (`delete_event` → `DeleteItem` drops the key); a **work item is
  never deleted, only archived**, so its GSI2 key is maintained by
  `update_work_item` when `due_at` is set/changed/cleared, and dropped on
  `archive_work_item` (an archived item leaves both the board and the calendar).

**WebSocket connection** (live sync, §4)
- PK `FAM#<familyId>` · SK `CONN#<connectionId>`
- attrs: `member_id`, `connected_at`
- (Co-located → "all of a family's connections" is a Query on `FAM#<familyId>`
  with `begins_with(CONN#)`.)

### 1.3 Access patterns → operations (all single-op)
| Need | Operation |
|---|---|
| Load a work item + its log + checklist | `GetItem` PK=`FAM#f` SK=`WI#id` |
| Append a human/assistant update | `UpdateItem` (`list_append` on `updates`) |
| Set due / status / assign / tag | `UpdateItem` on the one item |
| The board (4 columns, ordered) | `Query` GSI1 PK=`FAM#f#BOARD` (pre-sorted by status, position) |
| The calendar (events + due items in range) | `Query` GSI2 PK=`FAM#f#CAL`, SK between `TS#<from>` and `TS#<to>` |
| List members | `Query` PK=`FAM#f` `begins_with(SK, MEM#)` |
| List a family's live connections | `Query` PK=`FAM#f` `begins_with(SK, CONN#)` |
| Resolve a device token | `GetItem` PK=`TOK#<hash>` |
| Archive a work item | `UpdateItem` set `archived_at` + **remove GSI1 keys** |
| Archive all done | `Query` GSI1 for `STATUS#done#*`, then per-item `UpdateItem` |

### 1.4 Atomicity (HLD §6)
- **Intra-item = `UpdateItem`** (atomic by construction) — the hot path; no
  unit-of-work needed.
- **Cross-item = `TransactWriteItems`**, only two cases:
  1. **Confirm that co-creates an event:** `Put` the event item **+** `UpdateItem`
     appending the `source=assistant` log entry to the work item (two partitions,
     atomic). Within the 100-item/4MB transaction limits (comfortable at
     household scale).
  2. **Future spill truncate** (§1.5) — not built v1.
- **Concurrency:** last-write-wins via `updated_at`; `UpdateItem` condition
  expressions available where we want stricter (e.g. archive-only-if-`done`).

### 1.5 S3 log spill — designed-for, NOT built (HLD §6)
- The item reserves `log_segments` + keeps `updates` ordered so spill is possible
  without a schema change.
- When built: write the immutable S3 segment **first** (idempotent, keyed by
  `(workItemId, from_ts, to_ts)`), **then** `UpdateItem` to truncate `updates` and
  append the `log_segments` pointer. S3 ∉ `TransactWriteItems`, so ordering +
  idempotency carry correctness. The **labor view** (whole-history reader) merges
  Dynamo + S3. Trigger: nested-`updates` size > ~200KB (margin under the 400KB
  item cap). Deferred — at household volume this is years off.

---

## 2. The repository (persistence seam)

The seat the SQLAlchemy `Session` used to hold on `NtakeActionContext` (HLD §6).
A narrow interface the action handlers depend on; the engine stays
persistence-ignorant (boundary test forbids `boto3` there).

### 2.1 Interface (method set, derived from the action handlers)
```
class Repository(Protocol):
    # reads
    def get_work_item(self, family_id, work_item_id) -> WorkItem | None
    def get_member(self, family_id, member_id) -> Member | None
    def list_members(self, family_id) -> list[Member]
    def get_event(self, family_id, event_id) -> Event | None
    def list_board(self, family_id) -> dict[str, list[WorkItem]]
    def list_calendar(self, family_id, frm, to) -> list[CalendarRow]
    def list_done_work_items(self, family_id) -> list[WorkItem]
    def list_work_items(self, family_id) -> list[WorkItem]   # all non-archived (done included); LINK world-view + deep-context assignee scan (§3.1)
    def list_events(self, family_id) -> list[Event]          # all events (full DTOs); LINK world-view window + deep-context participant scan (§3.1)
    def get_family(self, family_id) -> Family | None
    # writes (intra-item → UpdateItem; marked ones → TransactWriteItems)
    def put_work_item(self, wi) -> None
    def update_work_item(self, family_id, work_item_id, changes) -> None   # if due_at set/changed/cleared, maintain GSI2 key accordingly
    def append_update(self, family_id, work_item_id, update) -> None
    def put_event(self, ev) -> None                                # standalone create
    def update_event(self, family_id, event_id, changes) -> None   # reschedule/loc/tags/participants
    def create_event_from_update(self, ev, wi_log_entry) -> None   # TransactWriteItems (co-created)
    def delete_event(self, family_id, event_id) -> None            # DeleteItem + drop GSI2 key (events delete; work items only archive)
    def archive_work_item(self, family_id, work_item_id) -> None   # + drop GSI1 (GSI2, if due-dated, is also dropped so an archived item leaves the calendar)
    # connections (live sync)
    def put_connection(self, family_id, connection_id, member_id) -> None
    def list_connections(self, family_id) -> list[str]
    def delete_connection(self, family_id, connection_id) -> None
```
- **No `commit()`** — there is no deferred unit of work. Each method is one atomic
  DynamoDB op (or one `TransactWriteItems` for the two cross-item methods). This
  is the HLD §6 "no unit-of-work interface" decision made concrete.
- **`list_work_items` / `list_events` (added for LINK, §3.1).** Both are
  family-partition reads returning full DTOs — `list_work_items` excludes archived
  items (done included), `list_events` returns every event. They back the LINK
  world-view (window-filtered in code) and deep-context (assignee / participant
  scans), which `list_board` (grouped, loses order) and `list_calendar` (thin
  `CalendarRow`, no timing/participant fields) cannot serve. In DynamoDB both are a
  single `Query` on the family partition (`PK=FAM#<fam>`, `begins_with(SK, WI#|EV#)`),
  no new GSI. **Dynamo impl is a Tier-2 follow-up** (added when the capture path's
  dev integration lands); the InMemory impl ships with Session 4.
- The handler-facing conditional log append (only a work-item target logs; the
  `logs` flag) is realized by `append_update` being called inside the targeted
  handlers, exactly as today.

### 2.2 Two implementations
- **`InMemoryRepository`** — dicts; the fast unit-test double (replaces the old
  SQLite fixtures). Deterministic, no network.
- **`DynamoRepository`** — boto3 over the single table; owns the key composition
  (§1), the sparse-GSI write rules, and the two `TransactWriteItems`. The **only**
  place table-key knowledge lives.
- Both satisfy the same `Protocol`; Tier-1 tests run handlers against the
  in-memory one, and the same flow tests + access-pattern tests run
  `DynamoRepository` against the **real dev-stage table** via `make integration`
  (Tier 2 — no DynamoDB Local).
- **DTO types** (`WorkItem`, `Event`, `Member`, `Family`, `CalendarRow`) are the
  lifted Pydantic schemas from `app/schemas.py`, with int ids → **ULID strings**
  (§1). `CalendarRow` is a small new DTO unifying an event or a due-dated work
  item for the calendar Query (title, `sort_ts`, kind, id).

---

## 3. Assistant — the two Anthropic-API seams

> **Pivot note (2026-10):** these seams were originally designed on **Amazon
> Bedrock** (Converse). Bedrock invocation is **blocked by an account-level hold**
> on `111037110464` (full diagnosis in §3.5), so the seams move to the **Anthropic
> Messages API** (`POST https://api.anthropic.com/v1/messages`) called directly
> over HTTPS with an API key. This is a **provider swap, not a redesign** — the
> LINK ⇒ PROPOSE pipeline, the registry→tools projection, enum-over-whitelist, and
> the scriptable seam are all unchanged; only the wire protocol and the credential
> path differ. The deferred GENERATE⇒DECIDE / Jev exploration is recorded in §3.6.

Two distinct Anthropic calls with **different shapes** (HLD §7). Both go through
the Messages API; LINK uses plain constrained output, PROPOSE uses tool-use. Both
degrade to a safe empty result on any error (never raise into the request path),
preserving the current graceful-degrade posture. **Auth:** the Secrets Manager
secret `ntake-<stage>/anthropic-api-key` holds a JSON object
`{"api_key", "workspace_id"}`, read at Lambda cold start (§6/§7), never from code
or env; calls set `x-api-key`, `anthropic-version`, and `anthropic-workspace-id`
headers. *(The key in use is account-level, so the workspace-id header is
required; a workspace-scoped key would drop that header but the JSON shape is
retained either way.)*

### 3.1 LINK — constrained-JSON grounding
- **Input:** the world view (family's members, candidate work items/events as
  id+label lists) + the capture text + `now`/timezone. **Source (matches current
  code):** `now = datetime.now(UTC)` from the server clock at request time, and
  `timezone` from the family item's `timezone` attribute (§1.2) — not client-
  supplied. All family-local ↔ UTC conversion uses the lifted `temporal.py`
  (NFR-TIME).
- **Call — forced-tool (DECIDED, probe-verified 2026-10).** A Messages request
  with a `system` prompt instructing "resolve which existing entities this note
  refers to," the world+note as the `user` message, and a **single forced tool**
  `record_links` whose `input_schema` *is* the object
  `{work_item_ids: [int], event_ids: [int], member_ids: [int]}`, forced via
  `tool_choice: {"type": "tool", "name": "record_links"}`. The answer is read
  directly from the response's `tool_use` block `.input` — already a parsed
  object, no text/JSON-string handling on the happy path.
  - **Why forced-tool over prompt-and-parse (`scripts/spike/link_probe.py`
    finding):** both return the correct ids, but the plain-prompt reply wrapped the
    JSON in a ` ```json ` fence **and** appended a `**Reasoning:**` prose essay
    despite "Return JSON exactly" — i.e. it needs fence-stripping + object
    extraction from prose (brittle). The forced tool returned
    `input = {'work_item_ids': [2], 'event_ids': [], 'member_ids': []}` cleanly,
    `stop_reason: "tool_use"`. Cost note: the tool schema roughly doubled input
    tokens (1286 vs 557) — negligible at household volume, worth the robustness.
  - **Still validate-don't-trust:** parse the `tool_use.input` defensively (ignore
    unknown response fields — the live API carries extras like `caller`,
    `inference_geo`), and validate every id against the family (below), so a
    non-conforming reply degrades rather than corrupts.
- **Grounding (validate-don't-trust):** every returned id is checked to belong to
  the family; unknown ids are dropped, **duplicates are de-duplicated**, and
  first-seen order is preserved (so the resolved whitelist on `FocusedContext` —
  and thus PROPOSE's enum-over-whitelist — carries each id at most once).
  Deterministic **first-person linking** (add
  the capturing member for `I/me/my`) is applied in code, not left to the model.
- **Output:** the resolved whitelist → the deep-context fetch (single-Query reads
  per §1.3) → `FocusedContext` for PROPOSE.
- LINK **never emits actions.**

### 3.2 PROPOSE — Messages tool-use over the registry
- **`tools`** is the registry projected to tools: one tool per `ActionSpec` —
  `name` = action name, `description` = `ActionSpec.description`, `input_schema` =
  the JSON Schema assembled from `params` (§3.3). This is the single source of the
  tool menu (the prose "tools view" is gone).
- **`tool_choice: {"type": "any"}`** — the model MUST use a registered tool, no
  free text. `no_action` is a registered tool, so "nothing to propose" is a normal
  selection. *(Anthropic `tool_choice`: `any` = "must use one of the provided
  tools, model's choice which"; `tool` = force a specific one. `any` is the
  PROPOSE intent.)*
- **ids as `enum`-over-whitelist:** for id-bearing params (`member_id`, and the
  target), the `input_schema` constrains the value to an `enum` of **LINK's
  resolved ids** — the model disambiguates *which* resolved entity but cannot
  fabricate one. **Defense-in-depth:** the handler re-validates every returned id
  against the whitelist regardless, so the grounding guarantee holds even if
  enum-constrained decoding is best-effort. *(Grounding, not privacy — household
  text/context still goes to the Anthropic API, HLD §2a.)*
- **Empty-whitelist edge (LINK degraded or genuinely resolved nothing):** an empty
  `enum` is invalid JSON Schema and would also force the model toward a tool it
  can't fill. The rule: when the whitelist for an id param is empty, **omit the
  id-bearing tools entirely** from `tools` for that request — the model is then
  left with only no-target tools and `no_action`, so a degraded LINK lands cleanly
  on `no_action` (or a standalone-create tool) rather than erroring. Never emit a
  tool whose required id param has an empty `enum`.
- **Target attachment:** the model picks the verb (tool) + any enum-selected
  member; the app attaches the concrete `target_id`/`target_type` from LINK's
  resolved ids (the current "attach target from resolved ids" step), so a tool
  call is executable by construction.
- **Selection, not execution:** the handler reads the response's `tool_use`
  block(s) (the Messages `content` is a list of blocks; a tool call is
  `{"type": "tool_use", "id", "name", "input"}`), maps each to a `ProposedAction`
  → proposal card, and **stops** — it **never** returns a `tool_result` and
  **never** loops. Execution happens only on human Confirm, via
  `ActionSpec.execute` over the repository (§2). This is the propose-and-confirm
  contract, preserved by deliberately not completing the agent loop.

### 3.3 Schema translation (`ActionSpec.params` → tool `input_schema`)
- Reuse the existing `DataType` → JSON-Schema-fragment projection (the enum member
  already carries its `json_schema`), assembling one `input_schema` object per
  action: `{type: object, properties: {<param>: <fragment>}, required: [...]}`,
  `required` derived from `Param.required`. Exclusive param groups
  (`exclusive_params`) map to the timed-vs-all-day split that already exists as
  separate action specs, so no `oneOf` gymnastics are needed.
- The **id enum injection** (§3.2) is applied per-request (the whitelist is
  request-specific), overlaying the static fragment for id params.
- This keeps one source of truth: the same `params` drive validation, the tool
  schema, and (today) the prose view — they cannot desync. *(The Anthropic tool
  `input_schema` is plain JSON Schema, same as the Bedrock `inputSchema.json` was —
  so this projection is unchanged by the pivot; only the envelope key differs.)*

### 3.4 The scriptable seam (deterministic tests)
- Both seams sit behind a small `AnthropicClient` protocol with a scripted test
  double (the `ScriptedLLM` analog): canned LINK JSON + canned `tool_use` blocks
  keyed off the input. LINK/PROPOSE flows are exercised with **no network and no
  model**, exactly as the current suite does. The real `AnthropicClient` (the
  `anthropic` SDK or a thin `requests`/`urllib` Messages call) is the only place
  the Anthropic API is reached.
- **Migration note:** the Session-1 harness shipped a `ScriptedBedrockClient`
  shaped like the Converse response (`output.message.content`, `toolUse`). Session
  4 re-homes it as the **Anthropic-shaped** double (top-level `content` list;
  `{"type":"tool_use","name","input","id"}` blocks; `stop_reason`), since no real
  Bedrock adapter was ever written against it (HLD decision §10). The *role* of
  the double — canned, substring-keyed, deep-copy-isolated, call-recording — is
  unchanged; only the response shape it mimics changes.

### 3.5 Multi-tool-call + the Bedrock hold (why the pivot)
- **Multi-tool-call — resolved by the pivot.** The design wants one capture →
  possibly several proposal cards, mapped to **multiple `tool_use` blocks in one
  response**. On Bedrock this was an *unverified* open risk (did one Converse turn
  return multiple `toolUse` blocks?). The **Anthropic Messages API supports
  parallel tool use natively** — a single assistant turn can emit multiple
  `tool_use` content blocks — so the risk **largely dissolves**. The handler
  consumes a **list** of `tool_use` blocks regardless, so it is correct for one or
  many with no reshape. *(Remaining to-verify, now a prompt-quality question, not
  a capability one: does the real Claude model actually emit multiple tool calls
  for a genuinely multi-intent note, or prefer one? Checked in the dev stage; if
  it prefers one, one-proposal-per-capture is the acceptable v1 fallback — a
  call-count behavior, not a reshape.)*
- **Loop bound shares the 30s capture budget (HLD §2):** the capture path spends
  LINK + PROPOSE sequentially inside the one 30s Lambda timeout (cold start +
  Anthropic egress latency included). If a PROPOSE loop is ever used as the
  multi-intent fallback, the bound must be **small (≤2 iterations)**. (Reversible:
  one-proposal-per-capture sidesteps the loop entirely.)

#### Why the seams left Bedrock — the account-hold diagnosis (historical record)
> The following is the Session 1.5 investigation that **caused** the pivot to the
> Anthropic API (HLD decision §10). It is retained as the rationale and as the
> condition under which Claude-via-Bedrock could become a future option — **not**
> as an open blocker for v1 (the Anthropic API is not subject to this hold).

The tracer-bullet deploy was run on dev to resolve the multi-tool-call + enum
questions against the real model. **Result: the real Converse call could not be
exercised** — the AWS account is **not authorized to invoke Bedrock**, and only
AWS can lift it. This is what moved the seams off Bedrock entirely.
- **Bedrock BLOCKED on account authorization (not a code/IAM/shape issue).** Every
  `Converse` call — even **plain text with no `toolConfig`** — returns
  `ValidationException: "Operation not allowed"` on this account, in us-east-1,
  for both Anthropic Claude (Haiku 4.5 via the `us.` inference profile) **and**
  Amazon Nova Lite. The Bedrock Playground (as root) likewise does not respond. A
  **support case has been filed** to enable Bedrock model invocation; this is a
  first-time, account-level, human-gated authorization that IAM/CDK cannot grant
  (anticipated by the Session 0.2 caveat). The scoped `bedrock:InvokeModel` IAM is
  correct (the call *reaches* Bedrock — "Operation not allowed", not
  `AccessDenied`).
- **CORRECTION (2026-10-02, verified against the official model-access doc + a
  symptom-matching re:Post thread) — the Session 0.2 "retired, nothing to
  manually grant, auto-enables" note UNDER-STATED the prerequisites.** How model
  access *should* work on a clean account, per
  `docs.aws.amazon.com/bedrock/latest/userguide/model-access.html`:
  (1) the invoking identity needs **AWS Marketplace perms**
  (`aws-marketplace:Subscribe`/`ViewSubscriptions`/`Unsubscribe`) for the
  first-invoke auto-subscription; (2) **Anthropic models require a one-time First
  Time Use (FTU) use-case form** — submitted once per account via the console
  model catalog or the `PutUseCaseForModelAccess` API, granted immediately — this
  is **self-service, NOT a support case**, and was missed by the 0.2 note; (3) a
  valid payment method. **Error-type disambiguation:** a missing FTU form /
  Marketplace perms yields **`AccessDeniedException`**; our symptom was
  **`ValidationException: Operation not allowed` on *every* model including
  first-party Nova Lite (which has no FTU form)** — that specific signature is a
  **new/dormant-account anti-fraud hold on the bedrock-runtime data plane**, which
  only AWS lifts (the support case is correct). **Account nuance:** this account
  is from ~2014–2016 with a card, so "new account" fits poorly; the dormant-/
  low-Bedrock-usage variant of the same hold is the fit.
- **`make bedrock-preflight` RESULT (2026-10-02) — hold CONFIRMED; Session 1.5 was
  right.** The new standalone probe (`scripts/bedrock_preflight.py`) run on
  `111037110464`: **Nova Lite Converse → `ValidationException: Operation not
  allowed`**, and Claude the same. Because Nova is first-party with **no FTU form
  and no Marketplace handshake**, its failure is conclusive — this is the
  account-level data-plane hold, **not** a form/perms/shape issue. So the support
  case remains the only path; also confirm a **real credit card** (not just promo
  credits) is on file (the common reason the hold persists). Two side facts the
  probe surfaced: (a) the **Anthropic FTU use-case form is NOT yet submitted** —
  it is a genuine *second* prerequisite (the 0.2 note missed it) but is
  **downstream of the hold** (submitting it now won't help until the hold lifts;
  Nova needs no form yet also fails), so submit it when convenient so it isn't a
  second surprise later; (b) the probe's Marketplace-perms check initially
  false-alarmed (`aws-marketplace` is not a boto3 client — fixed to use
  `marketplace-catalog`); it is non-decisive anyway (the Nova Converse result is
  the signal). **Re-run `make bedrock-preflight` whenever the ticket is touched;
  when Nova/Claude return OK the hold is lifted** → submit the FTU form (if not
  already), then backfill §3.5 via `scripts/bedrock_bisect.py`.
- **STRONGER CONFIRMATION (2026-10-02): the FTU form itself is blocked.**
  Attempting to submit the Anthropic use-case form (console / `PutUseCaseForModelAccess`)
  returns **"Your account is not authorized to perform this action. Please create
  a support case."** This proves the hold sits **above** the per-model form —
  there is no self-service path around it (the thing that would self-service it is
  itself gated by the same hold). The support case is therefore the **sole**
  unblock, not merely the recommended one. **File it as an Account & Billing case**
  (free on Basic Support — do NOT pick Technical, which needs a paid plan) at
  `console.aws.amazon.com/support/home`: subject ≈ *"Bedrock runtime 'Operation
  not allowed' on all models — request invocation hold lifted"*, body states that
  Converse/InvokeModel fail with `ValidationException: Operation not allowed` for
  **all** models incl. first-party Nova Lite, the FTU form returns not-authorized,
  control plane works, identity has AdministratorAccess, payment method on file,
  account ~2014–2016 — ask them to lift the account-level Bedrock invocation hold
  in us-east-1. Confirm a **real card** (not promo credits) is the default payment
  method in the Billing console first. Then it is a wait; re-run
  `make bedrock-preflight` when AWS responds.
- **Model id reality (recorded for Sessions 5/8):** the originally-pinned
  `anthropic.claude-3-haiku-20240307-v1:0` is **retired** ("model version has
  reached end of life"). Modern Claude models on this account are
  **inference-profile-only** (no bare ON_DEMAND id) — invoke via a
  `us.anthropic.claude-…` profile id, and the IAM must grant `bedrock:InvokeModel`
  on **both** the inference-profile ARN **and** the underlying foundation-model
  ARNs across the profile's regions (us-east-1/us-east-2/us-west-2). Only
  `amazon.nova-*` expose bare ON_DEMAND ids. The tracer/stack now pin
  `us.anthropic.claude-haiku-4-5-20251001-v1:0` with that widened (still
  model-scoped) IAM. (Nova was tried as a cheap ON_DEMAND substitute but its
  Converse tool-use contract differs and it hit the same account gate, so Claude
  — the design's actual assumption — is the pin.)
- **Model id reality — now moot for v1, kept for the Bedrock-fallback option.**
  The detail above (Claude on Bedrock is inference-profile-only; retired
  `claude-3-haiku`; widened model-scoped IAM) only applies **if** the seams ever
  move back to Bedrock. On the **Anthropic API** the model is just a string in the
  Messages request body (`anthropicModelId` stack prop, e.g. a current Haiku-class
  id) and there is no inference-profile/IAM complication — the key grants access,
  not an IAM model ARN.
- **Pivot closure.** The Bedrock-hold question is **no longer a v1 blocker**: the
  seams are on the Anthropic API, which the hold does not touch, so Sessions 4+
  build and validate the real model against Anthropic directly (not after an AWS
  support case). The Bedrock support case + `scripts/bedrock_preflight.py` /
  `bedrock_bisect.py` remain only as the path to *re-enable the Bedrock fallback*
  if ever wanted; they are off the critical path. The throwaway `tracer/` +
  `TracerStack` + Bedrock probe scripts are still deleted in Session 5 as planned.

### 3.6 Deferred refactor — GENERATE ⇒ DECIDE (Jev) — NOT in v1
Recorded so the design exploration behind the pivot is not lost; **nothing here is
built in v1** (the v1 assistant is the Claude-only LINK ⇒ PROPOSE above).

- **The idea.** Reorganize capture by *capability* rather than subject matter:
  **GENERATE** (Anthropic — produce only the irreducibly free-form strings:
  arbitrary datetimes, free titles, participant names) ⇒ **DECIDE** (a System-One
  decision model, **TypeSafe Jev** — every typed judgment over an enumerable set:
  which action(s) via `noul` fan-out, which target/member via `choice` over the
  in-family whitelist, which generated value binds to which slot), with a
  deterministic validate-don't-trust floor underneath both. Jev returns calibrated
  typed answers and *structurally cannot* emit free text, which is why GENERATE
  stays on Claude.
- **Why it was attractive.** Separates the two tool-use failure modes (selection
  vs. argument construction); puts the calibrated-confidence gate on the decision;
  dissolves the multi-tool-call question (N independent `noul`s); cheap/fast on the
  common "mark it blocked" path (often zero LLM calls). The supporting reasoning:
  routing/cascade literature favors extract-then-decide with a calibrated router.
- **Why it is deferred.** Jev is weeks-old, single-vendor, and its headline
  guarantees ("0% structured-output errors, cannot hallucinate," calibration) are
  largely vendor/early-blog claims; its routing/**binding accuracy on multi-value
  notes** is unproven on our shape. Shipping on Claude first de-risks the product;
  Jev becomes a measured optimization behind the stable LINK⇒PROPOSE seams.
- **Open questions a future spike must answer before adopting it** (these were
  going to be a throwaway `scripts/spike/` against the real Anthropic + Jev APIs,
  decoupled from AWS): does Jev do our DECIDE job at all; does it reject
  over-generated candidates (always-generate vs. a triage gate); multi-value
  binding accuracy; whether a calibrated `P(note has free-form content)` threshold
  separates cleanly enough to be a "2-way-door" cost lever (default-off prop).
- **Seam hygiene that keeps the door open (do in v1 anyway):** keep the assistant
  client protocol generic ("call a model with a prompt / typed questions, get a
  typed result") rather than hard-named to capture, so a future DECIDE engine and
  read-only insight surfaces can reuse the seam untouched. This is normal boundary
  discipline, not a Jev-specific build.
- **PROPOSE is factored at the action/parameter boundary — the designated split
  point (decided 2026-10; applies when PROPOSE is built, Session 5).** v1 PROPOSE
  is a **single** Anthropic tool-use call that both selects the verb/target and
  generates the params — but its code is split into three separable pieces so the
  future GENERATE⇒DECIDE reshape is a *localized swap*, not a rewrite:
  1. **action-space projection** — `registry → tools` schema (pure; `build_tools_schema`);
  2. **the model call** — the one swappable unit behind the `AssistantClient` seam
     (today: one Claude call; later: DECIDE picks verb+ids, GENERATE fills params);
  3. **result mapping** — `tool_use` block(s) → `ProposedAction` (id re-validate,
     target attach; pure).
  Only piece 2 changes under the refactor; pieces 1 and 3 and the `ProposedAction`
  output contract are unchanged, so nothing downstream (confirm/execute) moves.
  **This is structural readiness only** — v1 builds NO separate parameter-generator
  or decision-model interface (that is the refactor, YAGNI until then). A single
  tool-use call inherently fuses selection + generation inside the model; "split
  point" means the surrounding code is factored for the swap, not that v1 runs two
  stages.

---

## 4. Live sync — WebSocket + direct publish (HLD §8)

### 4.1 WebSocket API routes
- **`$connect`** — authorized by the same device-token check as REST, token
  passed as `?token=` (EventSource's successor still can't set headers at connect;
  mirrors the old SSE accommodation). On success, `put_connection(family_id,
  connectionId, member_id)` (§2) writes the `CONN#` item under the family
  partition.
- **`$disconnect`** — `delete_connection(family_id, connectionId)`.
- No custom routes beyond connect/disconnect — the channel is **server→client
  nudges only** (the client refetches; it never sends over the socket), matching
  the one-directional live-update need.

### 4.2 Publishing a change (direct from the execute boundary)
- The publish is a single helper, `publish_change(repo, family_id, entity, id,
  op)`, called **once, at the confirm/execute boundary**, immediately after the
  repository write returns. It `list_connections(family_id)` and, for each,
  `postToConnection` with `{entity, id, op}` via the API Gateway Management API.
- **Why one call site:** every mutation flows through the confirm/execute boundary
  (`apply_action` → repository), so there is exactly **one** place that publishes.
  This is the completeness discipline that replaces DynamoDB Streams — not
  per-handler publish calls.
- **Stale pruning:** a `postToConnection` returning **410 Gone** →
  `delete_connection` for that connectionId (lazy cleanup). Other errors are
  logged and swallowed (a dead socket must not fail the user's confirmed write).

### 4.3 The single-publish-boundary invariant (test)
- A test asserts that the only call site of `publish_change` is the execute
  boundary (and that `apply_action` always calls it on a successful write) — the
  structural guard that "no committed change goes unannounced" without Streams.
- **If this invariant ever can't hold** (a write path outside the boundary), the
  documented upgrade is DynamoDB Streams + a fan-out Lambda (HLD §8/§13) — flip it
  on and move `publish_change` behind the stream trigger.

---

## 5. Identity — Lambda authorizer + minting + enroll (HLD §9)

### 5.1 Token hashing (lifted from `app/identity/`)
- `hash_token(plaintext, secret) = HMAC-SHA256`, as today. The per-install
  **secret lives in Secrets Manager** (not a file/env); the authorizer and the
  minting path read it via the Secrets Manager API (cached per Lambda container).
- Only the **hash** is stored (`TOK#<hash>` item, §1.2); plaintext is never
  persisted.

### 5.2 Lambda custom authorizer
- A REQUEST authorizer on the HTTP API (and the WS `$connect`): extract the bearer
  token (or `?token=` for WS), `hash_token`, `GetItem PK=TOK#<hash>`, require
  `revoked_at` is null, resolve `member_id`/`family_id`.
- **Returns:** an allow IAM policy + a **context** map `{member_id, family_id,
  role}` that the handlers read (so handlers never re-resolve the token). A miss
  (unknown/revoked) → deny (indistinguishable to the caller, as today).
- Authorizer results are cached by API Gateway (short TTL) to avoid a DynamoDB
  lookup per request on a chatty client.

### 5.3 Minting (admin path, stack-run)
- An operator-invoked **admin Lambda** run with AWS creds (**not** a home-PC CLI,
  and not a local script — a small deployed Lambda is the decision): generate a
  **strong random token**
  (unchanged entropy — it's the primary internet boundary now), store
  `TOK#<hash>` with `family_id/member_id/label/created_at`, **print plaintext
  once**. `revoke` sets `revoked_at`; `list` enumerates a member's tokens.
- Hardening follow-on (not v1-blocking, HLD §9): an IP allowlist / second factor
  on this minting path specifically, since it mints credentials over the public
  internet.

### 5.4 Enrollment — `/enroll#token=` receive flow (HLD §9, Option A)
- Minting emits a URL `https://<cloudfront-domain>/enroll#token=<token>`; a **QR
  code encodes that URL** (and the same URL is a shareable link).
- The family member scans it with the **OS camera**, which opens the URL in the
  browser → the PWA's `/enroll` route runs client JS: read the token from the
  **URL fragment** (`location.hash` — the fragment is never sent to the
  server/CloudFront logs), `localStorage.setItem`, then `history.replaceState` to
  scrub it from the address bar + history, then route into the app.
- Thereafter every request reads `localStorage` and sends `Authorization: Bearer
  <token>` (`?token=` for the WS connect). **No in-app QR scanner** — the QR is a
  URL, the OS scans it, the only client code is reading a fragment param on load.
- (A short-lived human-typable **exchange code** that trades for a strong token is
  a later UX add; the device credential is never an 8-digit code.)

---

## 6. Assistant call logging → S3 (HLD §10)

- **When:** every LINK and PROPOSE Anthropic call, logged after the call returns
  (success or degrade).
- **Object:** one JSON per call, key `assistant-logs/<family_id>/<yyyy-mm-dd>/
  <ulid>.json`. Body (full-fidelity default): `{seam (link|propose), model_id,
  prompt_version, system, user, tools?, raw_response, resolved_ids,
  latency_ms, usage (in/out tokens), stop_reason, degraded (bool), at}`.
- **Fidelity switch:** the `assistantLogFidelity` stack prop (`full|metadata`,
  default `full`). `metadata` drops `system`/`user`/`raw_response`/`tools`
  (the household-text-bearing fields), keeping the operational metadata. The
  logging adapter reads the prop at construction (a Lambda env value set by CDK
  from the prop — the one legitimate deploy-time env use).
- **Retention:** a **180-day S3 lifecycle rule** on the `assistant-logs/` prefix
  (whole object expires).
- **IAM:** the capture Lambda gets `s3:PutObject` on
  `arn:aws:s3:::<logs-bucket>/assistant-logs/*` only.
- **Consumption:** the prompt-optimizer tooling reads a family/date range via
  `ListObjectsV2` + `GetObject` — offline, out of the request path.
- Posture: the third accepted tradeoff (HLD §2a) — flips "don't log raw household
  text by default." The logged prompt/reply is the same text that already transits
  the Anthropic API; this adds an at-rest copy under the family's own S3 bucket.

---

## 7. CDK stack layout + per-stage props (HLD §11)

### 7.1 Stack
One `NtakeStack`, instantiated per stage (`dev`/`prod`) in `us-east-1` /
`111037110464`. **CDK language: TypeScript** (the app code is Python; infra is TS
CDK — the `NtakeStageProps` interface in §7.2 is TS). Resources:
- **DynamoDB** single table (+ GSI1 board, GSI2 calendar, TTL attr reserved for
  future use), on-demand.
- **S3**: static-assets bucket + logs bucket (lifecycle rule). **Both buckets are
  private — Block Public Access on, no public bucket policy.** The static-assets
  bucket is reached *only* through CloudFront via an Origin Access Control (OAC);
  its bucket policy grants read to the CloudFront distribution alone, not the
  public. The logs bucket is written by the capture (Anthropic-calling) Lambda and
  read offline by the prompt-optimizer tooling — nothing serves it, so it has no
  public access and no CloudFront origin at all.
- **Lambdas**: app handlers, the authorizer, the WS connect/disconnect, the
  minting admin path. Each with a **tightly scoped role** (per-route least
  privilege — this is why native-ish thin handlers help: `secretsmanager:
  GetSecretValue` on the **Anthropic-key secret ARN** only on the capture path,
  `s3:PutObject` only on the logging adapter, table read/write scoped per handler).
  **The capture Lambda has a 30s timeout** (two sequential Anthropic calls, cold
  start + public-internet egress to `api.anthropic.com` included); other handlers
  keep short defaults. *(No `bedrock:InvokeModel` anywhere — the LLM pivot
  replaced it with the Secrets Manager key read, HLD §9/§10.)*
- **HTTP API** + **WebSocket API** + the REQUEST authorizer wiring.
- **CloudFront** in front of the static bucket + the HTTP API origin. Routes an
  API path behavior (e.g. `/api/*` or the REST prefixes) to the HTTP API origin
  and everything else to S3, so the PWA and the API share one origin (same-origin,
  no CORS — LLD §9). **SPA fallback:** a deep link like `/enroll` has no S3 object,
  so CloudFront maps 403/404 from the S3 origin to **`200 /index.html`** — the
  static shell loads and client JS reads `location.hash` (LLD §5.4). Without this,
  hitting `/enroll` directly 403s.
- **Secrets Manager** — **two secrets, both created empty by CDK** (the construct
  owns name/ARN/removal-policy/IAM wiring; the *values* are set out-of-band via
  `aws secretsmanager put-secret-value`, a `[HUMAN]` step, so no secret value ever
  enters the repo/template/CFN state): (1) the **HMAC token secret** (§5.1), and
  (2) the **Anthropic API key** (§3/§6). Prod secrets use `RETAIN`. Rotating the
  Anthropic key is the same `put-secret-value` call, no redeploy.
- **AWS Budgets** budget + alert (cost protection as code, not a console step).

### 7.2 Typed per-stage props
```
interface NtakeStageProps {
  stage: "dev" | "prod";
  anthropicModelId: string;        // small Claude model is the cost dial (Haiku-class)
  assistantLogFidelity: "full" | "metadata";  // default "full"
  apiThrottle: { rateLimit: number; burstLimit: number };
  removalPolicy: RemovalPolicy;    // dev: DESTROY; prod: RETAIN
  pointInTimeRecovery: boolean;    // dev: false; prod: true
  budgetUsd: number;
}
```
- **dev:** `DESTROY` + no PITR (disposable, easy teardown), looser throttle fine.
- **prod:** `RETAIN` + **PITR** (replaces the old weekly snapshot), tighter
  throttle (token is the primary boundary), the chosen Claude model.
- *(The Anthropic API key is **not** a stage prop — it is a Secrets Manager secret
  value set out-of-band, §7.1/§5.1. Props never carry secret material.)*

### 7.3 Deploy
- `cdk bootstrap` once (Phase 0 / `setup-aws.sh`). The **first deploy is the
  tracer-bullet slice (PLAN Session 1.5)**; the full stack deploys with
  `cdk deploy NtakeStack-dev` / `cdk deploy NtakeStack-prod` thereafter. No
  console. Prod data protected by the retention props so a `destroy`/bad deploy
  can't wipe family data.

---

## 8. Test strategy per tier

Two tiers (operating-model change, 2026-10-02): **Tier 1** is the fast local
`make check` gate (no AWS, no Docker, no DynamoDB Local); **Tier 2** is
`make integration` against the real dev stage, built up incrementally per session.
The **same** flow tests run both tiers — in-memory, then the real table.

| Tier | What | How |
|---|---|---|
| **T1 · Unit (logic)** | engine, action handlers, schemas, temporal, hashing | in-memory `InMemoryRepository` + scripted Anthropic seam; no network |
| **T1 · Boundary** | engine imports no `boto3`/`fastapi`/persistence; `publish_change` has one call site | import-/call-graph assertions (the AWS analogs of the old sqlalchemy-boundary test) |
| **T1 · Anthropic contract** | LINK JSON parse+validate; PROPOSE tool-use → cards; schema translation; enum re-validation; graceful degrade | scripted Messages responses (incl. malformed → degrade) |
| **T1 · Infra** | the stack synthesizes; IAM scoping; props differ dev/prod | `cdk synth` + assertions on the template |
| **T2 · Access patterns** | the single-table keys/GSIs, `UpdateItem`/`TransactWriteItems`, sparse-archive, calendar range | the **same** flow tests + Dynamo access-pattern tests, run by `make integration` against the **real `ntake-dev` table** |
| **T2 · Cloud seams** | IAM for real, **real Anthropic API** (tool-use, enum adherence, multi-tool-call §3.5, prompt quality, Secrets Manager key read + egress), API GW → authorizer → WebSocket post-back | `make integration` against the deployed `dev` stack, disposable data — grown incrementally (Sessions 3/6/7), consolidated in Session 8 |

Tier 1 runs locally with no AWS account (the fast inner loop and the default
gate); Tier 2 (`make integration`, **[HUMAN]-invoked**, credential-checked, can
`DEPLOY=1`) covers the cloud-only truths against the real dev stage as each
session's infra slice lands — continuous integration, not one end-stage waypoint.

---

## 9. Frontend — very simple static PWA (HLD §12a)

The old server-rendered HTMX fragments (`render_board`/`render_calendar` behind
`/board/view` and `/calendar/view`) **do not exist** in the AWS build — a static
host can't server-render. The frontend is a **very simple, hand-written vanilla-JS
PWA, no framework and no build step**, served static from S3+CloudFront.

- **Assets:** `index.html` + a small `app.js` + `app.css` + the PWA
  `manifest.webmanifest` + `sw.js` (pass-through service worker for
  installability) + `icon.svg`. Lifted/adapted from the current `web_shell.py`
  constants; no bundler.
- **Rendering:** `app.js` fetches the **JSON APIs** (`/board`, `/events`,
  `/work-items`, `/capture`, `/actions/confirm`) with the bearer token from
  `localStorage` and renders with plain DOM. **All API calls go through the same
  CloudFront domain as the static assets** (CloudFront routes an `/api/*` behavior
  — or the app's REST path prefixes — to the HTTP API origin, the rest to the S3
  origin). This is **same-origin by construction, so there is no CORS to
  configure** — the simplest option that meets the requirement, chosen over a
  second API-Gateway origin + CORS. The board-column / event-card
  structure is ported from `web.py`'s render functions into client JS (DRY: the
  JSON already carries every field those fragments showed). **Routes
  `/board/view` and `/calendar/view` are not built.**
- **Enrollment:** the `/enroll` page reads the token from `location.hash`,
  `localStorage.setItem`, `history.replaceState` to scrub (LLD §5.4).
- **Live sync:** open the WebSocket (`?token=`), and on a `{entity,id,op}` nudge
  refetch the affected JSON and re-render (replacing SSE→HTMX-reload). Reconnect
  re-syncs by refetching on open. (The WS connects directly to the API Gateway
  WebSocket endpoint — a separate `wss://` origin, not fronted by CloudFront;
  WebSocket connects aren't gated by CORS, and the `?token=` connect authorizes
  it.)
- **Proposal cards:** `/capture` returns proposals as JSON (the existing
  `CaptureResponse` DTO); `app.js` renders each as a Confirm/Dismiss card and
  POSTs the chosen action to `/actions/confirm`. Propose-and-confirm is unchanged.
- **Tests:** the enroll fragment-read + storage/scrub, and the WS-nudge→refetch
  logic, are the integration-testable units (jsdom or a thin harness); kept
  minimal, matching the "very simple client" scope.
