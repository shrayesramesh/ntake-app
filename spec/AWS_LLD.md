# Family Calendar + Work Items on AWS — Low-Level Design (LLD)

> Detailed design for the from-scratch AWS rebuild. Architecture is in
> [`AWS_HLD.md`](AWS_HLD.md); the phased build is in [`AWS_PLAN.md`](AWS_PLAN.md).
> This document fills in the concrete contracts the HLD deferred: single-table
> keys/GSIs, the repository method set, the Bedrock seams + schema translation,
> the WebSocket wiring, the Lambda authorizer + minting, Bedrock logging, the CDK
> stack layout, the test strategy per tier, and the frontend client.
>
> **Region:** `us-east-1`. **Account:** `111037110464`.
> **Conventions:** all timestamps stored **UTC** (ISO-8601, `Z`); ids are
> **ULID** strings; `family_id` is the partition dimension; every access pattern
> below is a single DynamoDB operation unless noted.

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
  returns events + due items in one pass.

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
    def get_family(self, family_id) -> Family | None
    # writes (intra-item → UpdateItem; marked ones → TransactWriteItems)
    def put_work_item(self, wi) -> None
    def update_work_item(self, family_id, work_item_id, changes) -> None
    def append_update(self, family_id, work_item_id, update) -> None
    def put_event(self, ev) -> None                                # standalone create
    def update_event(self, family_id, event_id, changes) -> None   # reschedule/loc/tags/participants
    def create_event_from_update(self, ev, wi_log_entry) -> None   # TransactWriteItems (co-created)
    def delete_event(self, family_id, event_id) -> None            # DeleteItem + drop GSI2 key
    def archive_work_item(self, family_id, work_item_id) -> None   # + drop GSI1
    # connections (live sync)
    def put_connection(self, family_id, connection_id, member_id) -> None
    def list_connections(self, family_id) -> list[str]
    def delete_connection(self, family_id, connection_id) -> None
```
- **No `commit()`** — there is no deferred unit of work. Each method is one atomic
  DynamoDB op (or one `TransactWriteItems` for the two cross-item methods). This
  is the HLD §6 "no unit-of-work interface" decision made concrete.
- The handler-facing conditional log append (only a work-item target logs; the
  `logs` flag) is realized by `append_update` being called inside the targeted
  handlers, exactly as today.

### 2.2 Two implementations
- **`InMemoryRepository`** — dicts; the fast unit-test double (replaces the old
  SQLite fixtures). Deterministic, no network.
- **`DynamoRepository`** — boto3 over the single table; owns the key composition
  (§1), the sparse-GSI write rules, and the two `TransactWriteItems`. The **only**
  place table-key knowledge lives.
- Both satisfy the same `Protocol`; tests run handlers against the in-memory one,
  access-pattern tests run `DynamoRepository` against **DynamoDB Local**.
- **DTO types** (`WorkItem`, `Event`, `Member`, `Family`, `CalendarRow`) are the
  lifted Pydantic schemas from `app/schemas.py`, with int ids → **ULID strings**
  (§1). `CalendarRow` is a small new DTO unifying an event or a due-dated work
  item for the calendar Query (title, `sort_ts`, kind, id).

---

## 3. Assistant — the two Bedrock seams

Two distinct Bedrock calls with **different shapes** (HLD §7). Both go through the
Converse API (`bedrock-runtime:Converse`); LINK uses plain constrained output,
PROPOSE uses tool-use. Both degrade to a safe empty result on any error (never
raise into the request path), preserving the current graceful-degrade posture.

### 3.1 LINK — constrained-JSON grounding
- **Input:** the world view (family's members, candidate work items/events as
  id+label lists) + the capture text + `now`/timezone. **Source (matches current
  code):** `now = datetime.now(UTC)` from the server clock at request time, and
  `timezone` from the family item's `timezone` attribute (§1.2) — not client-
  supplied. All family-local ↔ UTC conversion uses the lifted `temporal.py`
  (NFR-TIME).
- **Call:** `Converse` with a system prompt instructing "resolve which existing
  entities this note refers to," and a response constrained to the JSON object
  `{work_item_ids: [str], event_ids: [str], member_ids: [str]}`. (Converse has no
  "JSON mode" knob like the llamafile path; we constrain by (a) a strict prompt +
  (b) parsing defensively and (c) validating every id against the family — so a
  non-conforming reply degrades, it doesn't corrupt.)
- **Grounding (validate-don't-trust):** every returned id is checked to belong to
  the family; unknown ids are dropped. Deterministic **first-person linking** (add
  the capturing member for `I/me/my`) is applied in code, not left to the model.
- **Output:** the resolved whitelist → the deep-context fetch (single-Query reads
  per §1.3) → `FocusedContext` for PROPOSE.
- LINK **never emits actions.**

### 3.2 PROPOSE — Converse tool-use over the registry
- **`toolConfig.tools`** is the registry projected to tools: one `toolSpec` per
  `ActionSpec` — `name` = action name, `description` = `ActionSpec.description`,
  `inputSchema.json` = the JSON Schema assembled from `params` (§3.3). This is the
  single source of the tool menu (the prose "tools view" is gone).
- **`toolChoice: {any: {}}`** — the model MUST pick a registered tool, no free
  text. `no_action` is a registered tool, so "nothing to propose" is a normal
  selection. *(Confirmed from the Bedrock `ToolChoice` docs: `any` = "must request
  at least one tool, no text generated".)*
- **ids as `enum`-over-whitelist:** for id-bearing params (`member_id`, and the
  target), the `inputSchema` constrains the value to an `enum` of **LINK's
  resolved ids** — the model disambiguates *which* resolved entity but cannot
  fabricate one. **Defense-in-depth:** the handler re-validates every returned id
  against the whitelist regardless, so the grounding guarantee holds even if
  enum-constrained decoding is best-effort. *(Grounding, not privacy — household
  text/context still goes to Bedrock, HLD §2a.)*
- **Target attachment:** the model picks the verb (tool) + any enum-selected
  member; the app attaches the concrete `target_id`/`target_type` from LINK's
  resolved ids (the current "attach target from resolved ids" step), so a tool
  call is executable by construction.
- **Selection, not execution:** the handler reads the response's `toolUse`
  block(s), maps each to a `ProposedAction` → proposal card, and **stops** — it
  **never** returns a `toolResult` and **never** loops. Execution happens only on
  human Confirm, via `ActionSpec.execute` over the repository (§2). This is the
  propose-and-confirm contract, preserved by deliberately not completing the agent
  loop.

### 3.3 Schema translation (`ActionSpec.params` → tool `inputSchema`)
- Reuse the existing `DataType` → JSON-Schema-fragment projection (the enum member
  already carries its `json_schema`), assembling one `inputSchema` object per
  action: `{type: object, properties: {<param>: <fragment>}, required: [...]}`,
  `required` derived from `Param.required`. Exclusive param groups
  (`exclusive_params`) map to the timed-vs-all-day split that already exists as
  separate action specs, so no `oneOf` gymnastics are needed.
- The **id enum injection** (§3.2) is applied per-request (the whitelist is
  request-specific), overlaying the static fragment for id params.
- This keeps one source of truth: the same `params` drive validation, the tool
  schema, and (today) the prose view — they cannot desync.

### 3.4 The scriptable seam (deterministic tests)
- Both seams sit behind a small `BedrockClient` protocol with a scripted test
  double (the `ScriptedLLM` analog): canned LINK JSON + canned `toolUse` blocks
  keyed off the input. LINK/PROPOSE flows are exercised with **no network and no
  model**, exactly as the current suite does. The real `BedrockClient` (boto3
  Converse) is the only place `bedrock-runtime` is imported.

### 3.5 Multi-tool-call — verify + fallback (HLD §13 / PLAN 3d, 5c)
- The design wants one capture → possibly several proposal cards, mapped to
  **multiple `toolUse` blocks in one Converse response**. This is **unverified**
  against the target Claude model and is confirmed early in the **tracer-bullet
  dev deploy (PLAN Part II, Session 1.5)**, then re-confirmed at full tool count
  in Session 8.
- **Fallback if a single turn yields one tool call:** either (a) loop PROPOSE a
  bounded number of times, or (b) accept one primary proposal per capture
  (acceptable for v1). The handler is written to consume a **list** of `toolUse`
  blocks either way, so the fallback is a call-count change, not a reshape.

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
- An operator-invoked admin path (a small admin Lambda or a `manage`-style script
  run with AWS creds — **not** a home-PC CLI): generate a **strong random token**
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

## 6. Bedrock call logging → S3 (HLD §10)

- **When:** every LINK and PROPOSE Converse call, logged after the call returns
  (success or degrade).
- **Object:** one JSON per call, key `bedrock-logs/<family_id>/<yyyy-mm-dd>/
  <ulid>.json`. Body (full-fidelity default): `{seam (link|propose), model_id,
  prompt_version, system, user, tool_config?, raw_response, resolved_ids,
  latency_ms, usage (in/out tokens), finish_reason, degraded (bool), at}`.
- **Fidelity switch:** the `bedrockLogFidelity` stack prop (`full|metadata`,
  default `full`). `metadata` drops `system`/`user`/`raw_response`/`tool_config`
  (the household-text-bearing fields), keeping the operational metadata. The
  logging adapter reads the prop at construction (a Lambda env value set by CDK
  from the prop — the one legitimate deploy-time env use).
- **Retention:** a **180-day S3 lifecycle rule** on the `bedrock-logs/` prefix
  (whole object expires). 
- **IAM:** the Bedrock-calling Lambda gets `s3:PutObject` on
  `arn:aws:s3:::<logs-bucket>/bedrock-logs/*` only.
- **Consumption:** the prompt-optimizer tooling reads a family/date range via
  `ListObjectsV2` + `GetObject` — offline, out of the request path.
- Posture: the third accepted tradeoff (HLD §2a) — flips "don't log raw household
  text by default."

---

## 7. CDK stack layout + per-stage props (HLD §11)

### 7.1 Stack
One `NtakeStack`, instantiated per stage (`dev`/`prod`) in `us-east-1` /
`111037110464`. **CDK language: TypeScript** (the app code is Python; infra is TS
CDK — the `NtakeStageProps` interface in §7.2 is TS). Resources:
- **DynamoDB** single table (+ GSI1 board, GSI2 calendar, TTL attr reserved for
  future use), on-demand.
- **S3**: static-assets bucket (behind CloudFront) + logs bucket (lifecycle rule).
- **Lambdas**: app handlers, the authorizer, the WS connect/disconnect, the
  minting admin path. Each with a **tightly scoped role** (per-route least
  privilege — this is why native-ish thin handlers help: `bedrock:InvokeModel`
  only on the capture path, `s3:PutObject` only on the logging adapter, table
  read/write scoped per handler). **The capture Lambda has a 30s timeout** (two
  sequential Bedrock calls); other handlers keep short defaults.
- **HTTP API** + **WebSocket API** + the REQUEST authorizer wiring.
- **CloudFront** in front of the static bucket + the HTTP API origin.
- **Secrets Manager** secret (the HMAC token secret).
- **AWS Budgets** budget + alert (cost protection as code, not a console step).

### 7.2 Typed per-stage props
```
interface NtakeStageProps {
  stage: "dev" | "prod";
  bedrockModelId: string;          // small model is the cost dial (Haiku/Nova)
  bedrockLogFidelity: "full" | "metadata";   // default "full"
  apiThrottle: { rateLimit: number; burstLimit: number };
  removalPolicy: RemovalPolicy;    // dev: DESTROY; prod: RETAIN
  pointInTimeRecovery: boolean;    // dev: false; prod: true
  budgetUsd: number;
}
```
- **dev:** `DESTROY` + no PITR (disposable, easy teardown), looser throttle fine.
- **prod:** `RETAIN` + **PITR** (replaces the old weekly snapshot), tighter
  throttle (token is the primary boundary), the chosen model.

### 7.3 Deploy
- `cdk bootstrap` once (Phase 0 / `setup-aws.sh`). The **first deploy is the
  tracer-bullet slice (PLAN Session 1.5)**; the full stack deploys with
  `cdk deploy NtakeStack-dev` / `cdk deploy NtakeStack-prod` thereafter. No
  console. Prod data protected by the retention props so a `destroy`/bad deploy
  can't wipe family data.

---

## 8. Test strategy per tier

| Tier | What | How |
|---|---|---|
| **Unit (logic)** | engine, action handlers, schemas, temporal, hashing | in-memory `InMemoryRepository` + scripted Bedrock seam; no network |
| **Boundary** | engine imports no `boto3`/`fastapi`/persistence; `publish_change` has one call site | import-/call-graph assertions (the AWS analogs of the old sqlalchemy-boundary test) |
| **Access patterns** | the single-table keys/GSIs, `UpdateItem`/`TransactWriteItems`, sparse-archive, calendar range | `DynamoRepository` against **DynamoDB Local** |
| **Bedrock contract** | LINK JSON parse+validate; PROPOSE tool-use → cards; schema translation; enum re-validation; graceful degrade | scripted Converse responses (incl. malformed → degrade) |
| **Infra** | the stack synthesizes; IAM scoping; props differ dev/prod | `cdk synth` + assertions on the template |
| **Dev-stage integration** (cloud) | IAM for real, **real Bedrock** (tool-use, enum adherence, multi-tool-call §3.5, prompt quality), API GW → authorizer → WebSocket post-back | deployed `dev` stack, disposable data (PLAN Session 1.5 tracer bullet, then Session 8 full-stack) |

The first five tiers run locally with no AWS account; only the last needs the dev
stage — the division the plan is built around (local-first, cloud only for
cloud-only truths).

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
  `localStorage` and renders with plain DOM. The board-column / event-card
  structure is ported from `web.py`'s render functions into client JS (DRY: the
  JSON already carries every field those fragments showed). **Routes
  `/board/view` and `/calendar/view` are not built.**
- **Enrollment:** the `/enroll` page reads the token from `location.hash`,
  `localStorage.setItem`, `history.replaceState` to scrub (LLD §5.4).
- **Live sync:** open the WebSocket (`?token=`), and on a `{entity,id,op}` nudge
  refetch the affected JSON and re-render (replacing SSE→HTMX-reload). Reconnect
  re-syncs by refetching on open.
- **Proposal cards:** `/capture` returns proposals as JSON (the existing
  `CaptureResponse` DTO); `app.js` renders each as a Confirm/Dismiss card and
  POSTs the chosen action to `/actions/confirm`. Propose-and-confirm is unchanged.
- **Tests:** the enroll fragment-read + storage/scrub, and the WS-nudge→refetch
  logic, are the integration-testable units (jsdom or a thin harness); kept
  minimal, matching the "very simple client" scope.
