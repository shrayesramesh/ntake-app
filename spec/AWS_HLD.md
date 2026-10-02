# Family Calendar + Work Items on AWS — High-Level Design (HLD)

> **Status:** agreed. Detailed design is in [`AWS_LLD.md`](AWS_LLD.md); the
> phased build is in [`AWS_PLAN.md`](AWS_PLAN.md).
> **Framing:** a **from-scratch, AWS-native rebuild** of the product — not a
> migration, strangler, or port of the self-hosted app. The existing repo is
> **reference** for behavioral contracts and infra-agnostic logic (the action
> engine/registry, action specs, Pydantic schemas, temporal handling, device-token
> hashing). Nothing about its *runtime* (FastAPI-on-a-home-PC, SQLAlchemy, SQLite,
> Alembic, SSE, Tailscale, systemd, `VACUUM INTO`) carries over as framing.
> This document is deliberately high-level; keys/GSIs, IAM, schema translation,
> and handler detail live in the forthcoming LLD.

---

## 1. Goals & non-goals

### Goals
- Build the product as a **serverless AWS stack**: CloudFront + API Gateway
  (HTTP + WebSocket) + Lambda + DynamoDB + Bedrock, defined entirely in **CDK**.
- Preserve the product's **behavioral contracts**: propose-and-confirm (never
  auto-apply), the append-only work-item update log, `family_id` scoping,
  device-token identity + attribution, live push to the wall display (DISP-2),
  UTC storage / family-local render (NFR-TIME).
- **Reuse infra-agnostic code** — the engine, action registry + specs, schemas,
  temporal helpers, token hashing — lifted into the new app unchanged.
- **Clean, reproducible deploys**: one-command stand-up/teardown, dev + prod as
  isolated stages, prod data protected by retention policy.
- **Local-first iteration**: the logic and data-access layers testable locally
  with no AWS account, so the cloud is only needed for genuinely cloud-only seams.

### Non-goals (this phase)
- Multi-tenant / multi-household scaling beyond what single-table DynamoDB gives.
- Cognito (device tokens are retained — see §9).
- Separate dev/prod **accounts** (one account, two stages — see §11).
- Building the S3 log-spill subsystem (designed-for, not built — see §6).
- `.ics` interop, labor view, backfill — unchanged in priority; not part of the
  platform build.

---

## 2. Agreed decisions

1. **From-scratch rebuild.** New AWS-native app; no SQLAlchemy, no local-app
   survival, no strangler. Infra-agnostic domain code is lifted in; runtime is
   all new.
2. **Compute: Lambda, thin shape-agnostic handlers.** The "FastAPI+Mangum vs.
   native handlers" question is deliberately demoted: the domain logic lives in
   the registry + repository + the Bedrock agent loop, so the HTTP handlers hold
   almost no logic and the envelope shape barely matters. Handlers are thin I/O.
   **Languages:** the application (handlers, core, adapters) is **Python** (lifts
   the existing core directly); the **infra/CDK is TypeScript**. **Capture-path
   Lambda timeout: 30s** (covers the two sequential Bedrock calls); memory sized
   in the LLD, provisioned concurrency only if measured need.
3. **Data model: DynamoDB single table, idiomatic, reshaped for access patterns**
   (not a 1:1 translation of the 7 relational tables). See §6.
4. **Persistence seam: a repository carried in the action context** (the seat the
   SQLAlchemy `Session` used to occupy) — **no separate unit-of-work interface**,
   because the single-item work-item model makes the hot path atomic on its own.
   See §6.
5. **Assistant: two Bedrock seams.** LINK = deterministic grounding via a
   constrained-JSON seam; PROPOSE = **Bedrock Converse tool-use** over the
   registry-as-`toolConfig`. Execution stays behind human Confirm. See §7.
6. **LLM tier: Amazon Bedrock**, chosen deliberately over SageMaker / self-hosted
   (options in §7a); model size is the cost dial.
7. **Identity: device tokens**, promoted to the primary security boundary now
   that Tailscale is gone, enforced by a **Lambda custom authorizer**. See §9.
8. **Live sync: API Gateway WebSocket API, published directly from the confirm/
   execute boundary** — the handler posts the change to the family's connections
   right after it commits. No DynamoDB Streams, no fan-out Lambda (fewer moving
   parts). Streams is the noted hardening upgrade (§13). See §8.
9. **Infra: CDK**, single account, **dev + prod stages**, local-first testing with
   a cloud **dev stage** as the integration waypoint. See §11.

---

## 2a. Posture changes vs. original requirements (three accepted tradeoffs)

The AWS build deliberately relaxes three constraints from the original
`REQUIREMENTS.md`. All three are **accepted tradeoffs**, recorded here so they are
explicit, not emergent:

- **NFR-PRIVACY — downgraded from hard constraint to accepted tradeoff.** The
  original design kept all family data and messages on owned hardware with **no
  third-party cloud in the data path**. The AWS build stores household data in
  **DynamoDB** and routes capture text through **Bedrock**; data now lives in and
  transits a managed cloud. (Available mitigations if ever wanted: Bedrock's
  no-training-on-input posture, VPC/PrivateLink, CMK encryption, region pinning —
  but data still leaves owned hardware.) This downgrade is what makes the whole
  Dynamo + Bedrock direction coherent rather than a violation.
- **NFR-COST — changed.** The original "essentially electricity" story
  (self-hosted, local model, no per-call fees) becomes **per-call Bedrock cost +
  managed-service charges** (API Gateway, Lambda, DynamoDB, CloudFront, WebSocket
  minutes). Still low at a 2–4 person household's volume and scale-to-zero helps;
  the cost dial is model size (§7a). No longer zero-marginal-cost per capture.
- **Bedrock-call logging default — flips a privacy sub-rule.** The original
  observability rule was "do not log raw household note text by default." The AWS
  build logs **full-fidelity** Bedrock calls (prompt + reply) **by default** to
  enable prompt improvement, opt-out to metadata-only via a CDK stack prop, with a
  180-day S3 lifecycle-rule expiry (stored in S3, not the table — see §10). See §10.

Everything else (propose-and-confirm, append-only log, `family_id` scoping,
device-token identity + attribution, live push, UTC/family-local time) is
preserved.

---

## 3. Target topology

```
         Family phones (PWA)              Wall display (PWA kiosk)
                │                                  │
                └───────────────┬──────────────────┘
                                │  HTTPS (public, TLS at the edge)
                                ▼
                        ┌───────────────┐
                        │  CloudFront   │  static PWA assets + API origin
                        └───────┬───────┘
                   ┌────────────┴─────────────┐
                   ▼                            ▼
        ┌──────────────────┐        ┌───────────────────────┐
        │  API GW HTTP API │        │  API GW WebSocket API  │
        │  (REST routes)   │        │  (live sync)           │
        └────────┬─────────┘        └───────────┬────────────┘
     Lambda authorizer (device token → member)  │ $connect / $disconnect
                 ▼                                ▼
        ┌──────────────────┐           ┌──────────────────┐
        │  App Lambda(s)   │           │ connections (DDB)│
        │  thin handlers:  │           └──────────────────┘
        │  context-build → │                   ▲
        │  agent loop →    │                   │ postToConnection
        │  repo execute →  │───────────────────┘  (direct, right after commit:
        │  publish change  │                       look up the family's conns,
        └───┬──────────┬───┘                       post the {entity,id,op} nudge)
            │          │
            ▼          ▼
   ┌─────────────┐  ┌─────────┐
   │  DynamoDB   │  │ Bedrock │
   │ single table│  │(Converse│
   │             │  │ tool-use)│
   └──────┬──────┘  └─────────┘
          │
          ▼
   (future) S3 — cold work-item log segments (escape hatch, not built v1)
   (future) DynamoDB Streams — completeness-by-construction upgrade (not built v1)
```

Tailscale is **gone**: its only job was being the network perimeter for a home PC
with no public endpoint; CloudFront + API Gateway + the authorizer are the
perimeter now.

---

## 4. Request flows

### 4.1 Capture → propose (the daily loop)
1. PWA sends capture text with the device token.
2. The **authorizer** resolves the token → member (§9); the handler loads the
   family's **focused context** (single-Query reads, §6).
3. **LINK** (Bedrock constrained-JSON seam) resolves which existing entities the
   text refers to → their real ids, validated against the family (grounding).
4. **PROPOSE** (Bedrock Converse tool-use) selects action(s) from the
   registry-as-`toolConfig` and fills typed args, with ids constrained to LINK's
   whitelist. Returns tool-use blocks → proposal cards. **Nothing is written.**
5. Cards return to the author's device for Confirm / Dismiss.

### 4.2 Confirm → execute
1. The PWA sends back the chosen action (name + params + target).
2. The handler dispatches via the registry: `ActionSpec.execute(params, ctx)`,
   where `ctx` carries the **repository**. The handler mutates and (for work-item
   targets) appends a `source=assistant` log entry.
3. The repository commits — one `UpdateItem` for the common single-item case; a
   `TransactWriteItems` for the cross-item cases (§6).
4. Right after the commit, the handler **publishes the change directly**: it looks
   up the family's active WebSocket connections and `postToConnection`s the
   `{entity, id, op}` nudge, so every connected device refetches (§8).

Dismiss writes nothing. Correcting a proposal = restate (unchanged contract).

---

## 5. Package shape

```
ntake-aws/                     ← new AWS-native application
  infra/                       ← CDK app: HTTP API, WS API, DynamoDB (+ TTL,
                                 GSIs), Lambdas, CloudFront, S3 (static assets +
                                 Bedrock-logs bucket w/ lifecycle rule), IAM,
                                 authorizer wiring; per-stage props (dev/prod)
  handlers/                    ← thin Lambda handlers (REST, ws_connect/disconnect)
  adapters/
    dynamo_repository.py       ← the repository over the single table (owns the
                                 TransactWriteItems for cross-item cases)
    bedrock_link.py            ← LINK: constrained-JSON Converse seam
    bedrock_propose.py         ← PROPOSE: Converse tool-use seam
    ws_publisher.py            ← direct postToConnection to a family's conns
                                 (called at the confirm/execute boundary)
    authorizer.py              ← device-token Lambda authorizer
    bedrock_log.py             ← full-fidelity Bedrock call logging → S3 (§10)
  core/  (lifted, infra-agnostic — reused unchanged)
    engine/                    ← registry, ActionSpec, dispatch, propose contract
    actions/                   ← the ntake action specs + handlers
    schemas, temporal, token hashing
  tests/                       ← in-memory fake repo (fast), DynamoDB Local
                                 (access patterns), scripted Bedrock seams,
                                 cdk synth assertions
```

**Boundary discipline (carried over + extended):** the engine imports nothing
infra-specific — today a test forbids `sqlalchemy`/`fastapi` there; the AWS
version forbids `boto3` in the engine for the same reason. The registry stays a
persistence-ignorant **dispatcher**; persistence lives behind the repository in
`ctx`.

---

## 6. Data layer — DynamoDB single table (reshaped, not translated)

Single table, **partitioned by family**. Designed around the reads/writes the app
actually performs, so every app read is a single Query and every common write is a
single atomic item write. (Exact PK/SK + GSI keys in the LLD.)

### Work items — co-located single item
- A work item is **one DynamoDB item** holding its fields **plus** recent update
  log and checklist **nested** as attributes.
- **Common mutation = one atomic `UpdateItem`** (set due, change status, assign,
  tag, append a recent log entry) — no cross-item transaction, no partial-write
  window, so **no unit-of-work abstraction is needed on the hot path**.
- **Common read = one `GetItem`** (item + log + checklist together), replacing the
  three relational queries the detail view used to run.
- The nested log is an **ordered structure that reserves a slot for S3 segment
  pointers** — so the spill escape hatch is *possible* without being built.

### Events — flat single item
- An event is a **flat, small item** (title, timing, participants, tags,
  denormalized provenance). No child collection, no growth vector, so **no nesting
  or spill machinery** — it is naturally a single item far under limits.
- The denormalized **provenance snippet** (who/when/why) is written **onto the
  event** at confirm time; the `source_update_id` back-reference is optional and
  **resolve-on-read** (a deleted source update just blanks the backlink — matches
  the old SET-NULL intent without a cross-partition write).

### Access patterns → GSIs
- **Board:** a GSI keyed by status + position, with a **sparse key** so archived
  items simply drop out of the index — the board is one Query returning items
  pre-sorted by column then position; archiving = removing the GSI key.
- **Calendar:** a GSI keyed by a **unified time sort key** (`sort_ts` derived from
  the UTC instant for timed events / family-midnight for all-day) so the calendar
  is one time-ordered Query — resolving the old two-timing-representation
  awkwardness while keeping both stored fields for rendering.

### Keys, ids, concurrency
- **ULID ids** (time-sortable, **server/Lambda-generated** at write time) replace
  relational autoincrement. Record timestamps (`created_at`/`updated_at` etc.) are
  likewise **server-authoritative** (`datetime.now(UTC)` in the handler), matching
  today's model — the client never supplies an id or a stored timestamp. (The
  request's `now` is prompt-reasoning context only; see LLD §3.1.)
  Ripples into the API/schemas and the LLM-facing id handling (ids become opaque
  strings) — flagged for the LLD.
- `family_id` is the **partition dimension**, not a filtered column —
  multi-household isolation becomes a partition boundary.
- **Last-write-wins** concurrency preserved (an `updated_at` attribute); DynamoDB
  conditional writes available where we want stricter.
- `tags` / `participants` are native DynamoDB lists (no change).

### Atomicity
- **`UpdateItem`** for intra-item changes — the hot path, atomic by construction.
- **`TransactWriteItems`** reserved for the **cross-item** cases only: (a) a
  work-item update that **co-creates a calendar event** (event item + work-item
  log entry, two partitions, atomic), and (b) the future spill truncate step.
- The repository owns all of this; handlers never see `boto3`.

### S3 log spill — future escape hatch (not built v1)
- The one unbounded growth vector is a long-lived, chatty work item's log
  approaching the DynamoDB **400KB item ceiling**. The escape hatch: spill the
  oldest log entries to **S3** immutable segments, leaving a pointer in the item.
- **Not built in v1.** The item is *designed* so spill is possible (ordered log +
  reserved pointer slot); the spill subsystem is deferred like the original
  off-machine-backup capability — mechanism-ready, flip-on-later.
- **Why it's non-trivial (noted for when it's built):** S3 and DynamoDB cannot
  share one atomic transaction, so spill needs write-S3-first-then-truncate
  ordering with idempotent segments and a read-merge path; and the **labor view**
  (a whole-history reader) is the one surface that pays the merge cost. At
  household volume, hitting 400KB means thousands of entries on one item —
  plausibly years away. Accepted far-off risk.

---

## 7. Assistant on Bedrock — two seams

### LINK — deterministic grounding (constrained-JSON seam)
`bedrock_link` makes one constrained-JSON Converse call that returns
`{work_item_ids, event_ids, member_ids}`; the app validates these against the
family (validate-don't-trust) to produce the resolved whitelist. Deterministic
first-person linking (the capturing member for `I`/`me`/`my`) is preserved. LINK
never emits actions — it only grounds.

### PROPOSE — Bedrock Converse tool-use (over the registry)
- The **action registry projects onto `toolConfig`**: each `ActionSpec` →
  a tool (`name`, `description`, `inputSchema` from the typed `params`). This
  projection already exists (`build_tools_schema`) and becomes the single source
  of the tool menu — the parallel prose "tools view" largely dissolves, removing
  the view/schema desync risk.
- **`toolChoice: "any"`** forces the model to pick a registered tool (no free
  text), with **`no_action` as a registered tool** — this resolves the "nothing to
  propose" case cleanly. *(Confirmed from the Bedrock `ToolChoice` docs: `any` =
  "must request at least one tool, no text generated".)*
- **ids are constrained to LINK's whitelist as `enum`s** in the tool
  `inputSchema`, so the model can disambiguate *which* resolved entity ("assign to
  Sam") but **cannot fabricate** an id. **Defense-in-depth:** the app re-validates
  every returned id against the whitelist regardless, so the grounding guarantee
  holds even if enum-constrained decoding is best-effort rather than hard. *(Note:
  enum-over-whitelist is a **grounding** guarantee and a modest id-minimization,
  **not** a privacy measure — household text/context still goes to Bedrock per
  §2a.)*
- **Selection, not execution.** The handler takes the returned tool-use block(s),
  converts each to a **proposal card**, and **stops** — it never returns a
  `toolResult` and never loops. Execution happens only on human **Confirm**, via
  `ActionSpec.execute` over the repository. This is the hard propose-and-confirm
  contract, preserved by *not* completing the agent loop.
- **Multiple proposals:** one capture may yield several cards (a blocker flag *and*
  a due date). This maps to **multiple tool-use blocks in one response** —
  **flagged to-verify** against Bedrock/Claude. Fallback if a single turn returns
  one call: loop PROPOSE, or accept one primary proposal per capture (acceptable
  for v1).

### Determinism & tests
Scriptable Bedrock seams (the `ScriptedLLM` equivalent) keep PROPOSE/LINK tests
deterministic with no network. Prompt *quality* against real Claude is validated
in the **dev stage** (§11), not locally — the one thing local can't prove.

### 7a. LLM tier — options considered
- **Bedrock (chosen).** Turnkey serverless, first-class Converse tool-use (what
  the whole PROPOSE design rests on), model choice is config, scales to zero.
- **SageMaker.** Rejected: a real-time GPU endpoint is always-on and the most
  expensive option (idle ~99% at household scale), serverless SageMaker is
  CPU-only (too weak), and there's no managed tool-use. Only warranted by a
  weights-residency mandate (none here).
- **Self-hosted model called from Lambda (hybrid).** Rejected: reintroduces home-PC
  availability + cloud→home networking, and only *half*-preserves privacy (data
  still in DynamoDB), so it's incoherent once NFR-PRIVACY is an accepted tradeoff.
- **Cost dial (within Bedrock):** run LINK + PROPOSE on a **small model**
  (Claude Haiku / Nova) — both tasks are grounding/selection, not frontier
  reasoning. A per-stage config value, not an architecture change.

---

## 8. Live sync — WebSocket API, published direct from the execute boundary
1. PWA opens a WebSocket to the WS API; `$connect` (authorized via token query
   param, mirroring the old SSE accommodation) writes the `connectionId`, scoped
   to the family, to a **connections** item set.
2. On a confirmed write, the handler — **immediately after the repository
   commits** — looks up that family's active connections and `postToConnection`s
   the `{entity, id, op}` nudge.
3. The PWA refetches on the nudge — same client reaction as the old SSE, different
   transport (`EventSource` → `WebSocket`).
4. Stale connections (410 Gone) are pruned; `$disconnect` cleans up.

**Why direct-post over DynamoDB Streams (the simpler choice):** direct-post adds
**no** new infrastructure beyond the WS API + connections table — no Streams, no
fan-out Lambda, no stream-event wiring or its IAM/retry surface. The one thing it
gives up is *completeness-by-construction*: with Streams the trigger is the commit
itself, so a write can't be forgotten; with direct-post, "publish after commit" is
a responsibility of the write path.

**How we keep that risk small without Streams:** the publish lives at the **single
confirm/execute boundary** every mutation already flows through (not scattered
per-action), so there is **one** place to get right, not many. All v1 writes go
through that boundary. If a future write path ever bypasses it — or completeness
bugs appear — **DynamoDB Streams is the documented hardening upgrade** (§13):
flip it on, move the publish to a Streams-triggered fan-out, and the guarantee
becomes structural. Mechanism-ready, flip-on-later — the same posture as S3 spill.

---

## 9. Identity & auth — device tokens, promoted
- **Tailscale is gone**, so the device token is **no longer a secondary identity
  layer behind a trusted perimeter — it is now the primary security boundary**
  between the public internet and family data.
- **Minting is retained** (it's liked and now load-bearing): an operator action
  generates a random token, stores only its **HMAC hash** in DynamoDB, prints the
  plaintext once; `revoke` sets `revoked_at`. The *mechanism* moves from a home-PC
  CLI to an operator action against the deployed stack (a small admin **Lambda**
  run with AWS creds — concrete form pinned in LLD §5.3).
- **Enrollment / token delivery (the receive flow) — Option A, `/enroll#token=`.**
  The token stays **strong** (long, high-entropy) — it must, now that it's the
  primary internet-facing boundary — and the copy-paste pain is solved at
  *delivery*, not by weakening the secret. Minting emits a URL
  `https://<app>/enroll#token=<token>`; a **QR code encodes that URL** (and the
  same URL is a tappable enrollment link). The family member scans it with the
  **OS camera**, which opens the URL in the browser → the PWA's `/enroll` route
  reads the token from the **URL fragment** (`#…`, which is never sent to the
  server and so never hits access/CloudFront logs), persists it to `localStorage`,
  and `history.replaceState`s to scrub it from the address bar + history. Every
  request thereafter reads storage and sends `Authorization: Bearer <token>`
  (`?token=` for the WebSocket connect). This is why no in-app QR *scanner* is
  needed — the QR is just a URL, the OS scans it, and the only client code is
  reading a fragment param on load. (A short-lived human-typable **exchange code**
  that trades for a strong token is a possible later UX add; explicitly **not** an
  8-digit code as the standing credential — too weak for a public endpoint.)
- **Enforcement:** a **Lambda custom authorizer** hashes the presented bearer
  token (HMAC via a secret in **Secrets Manager / SSM**, not a file on a box) and
  resolves it to a member, returning an allow policy + member context. The
  WebSocket `$connect` authorizes the same way.
- **Hardening implied by the promotion:** API Gateway **throttling/rate limits**
  so a lost token can't be abused at volume; the secret in Secrets Manager.
- **Admin/minting path (v1):** token-only like the rest, **with a noted follow-on**
  to add a guard (IP allowlist / second factor) since it now mints credentials
  over the public internet. Cognito remains a possible future swap; out of scope.

---

## 10. Bedrock call logging (prompt improvement)
- **Every** LINK and PROPOSE Bedrock call is logged to enable prompt iteration:
  prompt-version/schema identity, model id, latency, token usage, finish reason,
  degrade-to-`{}` / empty flags, resolved ids — **plus**, by default, the **full
  prompt text and raw reply**.
- **Full-fidelity is the default** (opt-out, not opt-in). Opt-out to metadata-only
  is a **CDK stack prop** (`bedrockLogFidelity: "full" | "metadata"`, default
  `"full"`) — a deploy-time, typed, reviewable config, **not an env var** (env vars
  are deploy-baked in Lambda and wouldn't be a runtime knob anyway) and not a
  runtime flag. A future runtime toggle, if ever needed, is SSM/AppConfig.
- **Storage: S3** — one JSON object per call, keyed by family + date
  (`bedrock-logs/<family>/<date>/<ulid>.json`), so the prompt-optimizer tooling
  pulls a family/date range with a cheap `ListObjectsV2` + `GetObject` batch. S3 is
  the right home: these are large, write-once/read-rarely blobs read **offline in
  batches**, not in the request path — putting them in DynamoDB would spend
  hot-path item budget (and brush the 400KB item ceiling on a big PROPOSE prompt)
  on data the app never reads live. Keeping them out of the table also leaves the
  single table lean and keeps backup/PITR scope to family data only. The
  Bedrock-calling Lambda gets an `s3:PutObject` grant to this bucket (the only new
  IAM). *(If cheap aggregate queries over metadata are ever wanted without reading
  blobs, the future split is metadata → a queryable store, blobs → S3; v1 keeps
  everything in the one object.)*
- **Retention:** a **180-day S3 lifecycle rule** expires objects (the direct
  analog of a DynamoDB TTL; can also tier to cheaper classes before expiry if ever
  wanted). Kept simple — the whole object expires at 180 days.
- This is the third accepted posture change (§2a) — it flips "don't log raw
  household text by default".

---

## 11. Environments & deployment (CDK)
- **One AWS account, two stages — `dev` and `prod`.** Account-level isolation
  (separate billing/IAM/blast-radius) is an enterprise concern not warranted for a
  household; two stacks in one account give a safe cloud dev target without the
  separate-account overhead.
- **One CDK app, per-stage props.** `NtakeStack(dev)` / `NtakeStack(prod)`, each
  an isolated resource set (own table, Lambdas, APIs, CloudFront). Environment
  differences are **typed stack props**: `bedrockLogFidelity`, Bedrock model,
  throttle limits, and **removal/retention policy**.
- **Prod data protection:** prod DynamoDB is `RETAIN` + **point-in-time recovery**
  (replacing the old weekly `VACUUM INTO` snapshot) so a bad deploy or `destroy`
  can't wipe family data. Dev resources are `DESTROY` for easy teardown.
  (Production-safety: prod stores get retention/deletion protection by default.)
- **Local-first testing — what is and isn't provable locally:**
  - **Local (fast loop, no AWS):** domain logic via the **in-memory fake
    repository**; the single-table access patterns, GSIs, `UpdateItem` /
    `TransactWriteItems`, and TTL against **DynamoDB Local**; handlers invoked
    locally; `cdk synth` to validate infra compiles.
  - **Not provable locally (needs the dev stage):** **IAM** (no local enforcement —
    the #1 first-deploy failure), **Bedrock** (no local Bedrock — tool-use
    behavior, response shape, region availability, enum adherence, prompt quality),
    and the **API Gateway + authorizer + WebSocket post-back** loop (pure
    service-to-service plumbing).
  - **Therefore:** the **dev stage is the integration waypoint** — IAM, Bedrock
    tool-use/prompt-quality, and the live-sync loop are shaken out there, against a
    disposable table with fake data, **before every prod deploy**. "Deploy and know
    it works" is true for *logic*; the dev stage covers the cloud-only seams local
    testing structurally cannot.
- **Deployability:** everything (tables, GSIs, TTL, Lambdas, both APIs,
  CloudFront, IAM, authorizer) is CDK code — a fresh account goes empty → running
  with one `cdk deploy` per stage, reviewable in a CR, no console drift. A CI/CD
  pipeline is a natural follow-on, not required to start.

---

## 12. What's reused vs. built new

**Reused (lifted, infra-agnostic):** the propose/route/confirm **engine**, the
**action registry + specs**, Pydantic **schemas**, **temporal** helpers, **token
hashing**, and the propose-and-confirm + append-only-log + attribution contracts.

**Built new:** the **DynamoDB repository** (single-table, co-located items,
transaction-aware for cross-item cases), the **two Bedrock seams** (constrained-JSON
LINK + tool-use PROPOSE), the **WebSocket live-sync** (direct-post from the execute
boundary), the **Lambda authorizer**, **Bedrock-call logging**, the **CDK** stacks,
and the **thin HTTP handlers**.

**Carried over, with one real change — the frontend (§12a):** the operator
admin/minting **Lambda** (stack-run, not home-PC CLI — §9, LLD §5.3) and the demo
/ prompt-optimizer tooling carry over as-is. The PWA changes shape (static
client-render) — below.

### 12a. Frontend — a very simple static client, rendered from JSON
The self-hosted app served **server-rendered HTML fragments** from FastAPI
(`render_board` / `render_calendar` behind `/board/view` and `/calendar/view`,
swapped by HTMX). A static S3+CloudFront PWA **cannot** serve those — nothing
renders HTML at request time. Decision, scoped to a **very simple client**:

- **A static, hand-written vanilla-JS PWA — no framework, no build step.** Plain
  HTML + a little JS + CSS, served static from S3/CloudFront. This matches the
  original "minimal frontend for a read-mostly display" spirit, minus the
  server-rendered fragments a static host can't do.
- **Renders from the existing JSON APIs.** The client fetches `/board`,
  `/events`, `/work-items`, `/capture`, `/actions/confirm` (which already return
  the full records the old fragments were built from) and renders with plain DOM.
  The **fragment routes `/board/view` and `/calendar/view` are dropped** — no
  HTML-rendering Lambda.
- **Live sync:** the client subscribes to the WebSocket (`?token=`) and refetches
  the JSON on a nudge — replacing "SSE triggers an HTMX fragment reload."
- **Enrollment:** the `/enroll#token=` fragment-read flow (§9).
- **Not chosen:** Lambda-rendering HTML (keeps HTMX but adds a server-render
  Lambda and couples the API to HTML) and any SPA framework/bundler (too heavy for
  a 2–4 person read-mostly display). Revisit only if the plain client proves
  inadequate on-device.

---

## 13. Risks / open questions (for the LLD)
- **Multiple tool-use blocks per turn** — verify against Bedrock/Claude; fallback
  defined (loop or one-proposal-per-capture).
- **Enum-constrained decoding strictness** — mitigated by app-side whitelist
  re-validation; confirm behavior.
- **Single-table key/GSI design** — exact PK/SK, the two GSIs, the sparse-archive
  and unified-time keys, ULID formatting.
- **Nested-attribute update ergonomics** — conditional updates (archive-only-if-
  done), checklist check-off by name, position management inside nested lists.
- **Cross-item transaction scope** — the co-created-event `TransactWriteItems`
  shape; 100-item/4MB caps (comfortable at household scale).
- **Bedrock schema translation** — mapping the typed `params` to Converse tool
  `inputSchema`; LINK constrained-JSON shape; prompt-quality validation plan.
- **Cold starts** on the synchronous two-call capture path — latency budget;
  provisioned concurrency only if measured need.
- **ULID ripple** — API/schema id types and the LLM-facing id handling.
- **Admin/minting hardening** — the follow-on guard for the credential-minting
  path over the public internet.
- **Live-sync completeness** — direct-post relies on every write going through the
  one confirm/execute boundary; guard that invariant (a boundary test), and treat
  **DynamoDB Streams + fan-out** as the ready hardening upgrade if a write path
  ever bypasses it or completeness bugs appear.
- **Cost** — per-call Bedrock + managed-service posture (§2a); model-size dial.

---

## 14. Proposed next step — the LLD
Write the LLD in this order: (1) DynamoDB single-table schema + access patterns
(keys, the two GSIs, item shapes, ULID), (2) the repository interface + its one
DynamoDB implementation (incl. the cross-item `TransactWriteItems`), (3) the two
Bedrock seams + schema/tool translation + prompt-quality plan, (4) WebSocket
live-sync (connections table, direct-post from the execute boundary, 410 pruning),
(5) the Lambda authorizer + minting path, (6) Bedrock-call logging, (7) the CDK
stack layout + per-stage props, (8) the test strategy per tier (in-memory,
DynamoDB Local, dev-stage integration).
