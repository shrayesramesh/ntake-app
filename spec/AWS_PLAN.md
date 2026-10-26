# Family Calendar + Work Items on AWS — Build Plan

> The phased plan for the **from-scratch AWS-native rebuild**. Architecture is in
> [`AWS_HLD.md`](AWS_HLD.md); detailed design will be in the forthcoming AWS LLD.
> This supersedes the self-hosted `PLAN.md` for the AWS effort — `PLAN.md`
> describes the old home-PC build and is **not** the plan for this work.
>
> **Method:** TDD — tests first; the local gate (ruff + mypy + the test suite)
> must be clean before a checkpoint is done. Rule carried over from the original:
> **TDD the code you own; smoke-test the environment you don't** (here: AWS
> services — IAM, API Gateway — and the **Anthropic API** are validated in the
> cloud **dev stage**, not asserted locally).
>
> **Who does what:** steps tagged **[HUMAN]** are operator actions in the AWS
> console/CLI with the owner's own credentials (an agent must not do these).
> Steps tagged **[AGENT]** are code/infra an agent builds and tests. **[HUMAN]**
> steps are preconditions the CDK assumes; they are not in the app's CDK.

---

## Current state

Starting from scratch on AWS. The existing repo is **reference only** — reuse the
infra-agnostic core (engine, action registry + specs, schemas, temporal, token
hashing) and the behavioral contracts; nothing of the home-PC runtime (FastAPI
server, SQLAlchemy/SQLite, Alembic, SSE, Tailscale, systemd) carries over.

Account: `111037110464` — a **private (non-Amazon) AWS account**. Root user exists
**with MFA already enabled**. Nothing else is set up yet. **Region: `us-east-1`**
(pinned — used by the setup script and CDK config).

> **Assistant provider — the Anthropic API (not Bedrock).** The two assistant
> seams (LINK, PROPOSE) call the **Anthropic Messages API** directly over HTTPS
> with an API key stored in Secrets Manager — **not** Amazon Bedrock. Bedrock was
> the original choice but is blocked by an account-level invocation hold only AWS
> can lift; the seams pivoted to the Anthropic API (HLD decision §10, LLD §3.5).
> Anything below that still says "Bedrock" in a **Session 1.5 / Phase 0 historical
> note** is the record of what happened then; the **build target is the Anthropic
> API**. The pivot is a provider swap only — the LINK ⇒ PROPOSE pipeline, the
> registry→tools projection, and the scriptable seam are unchanged.

---

## Git strategy — a clean rebuild branch (do this first)

This is a ground-up rebuild sharing a repo with the app it replaces, so start it
on its **own long-lived branch**, clear out the home-PC runtime, and **keep (not
cherry-pick) the reusable modules**. Mechanics matter here:

- **Branch off `mainline`** (e.g. `aws-rebuild`). A rebuild this size must never
  happen on `mainline` — the branch isolates the multi-phase work and keeps the
  self-hosted app green and recoverable throughout. **Never reset or force-push
  `mainline`** (repo rule: committed history is immutable). The branch is purely
  additive; the old app stays intact on `mainline`.
- **Remove the home-PC runtime** on the branch: `git rm` the FastAPI server,
  SQLAlchemy/SQLite + Alembic, SSE emitter, Tailscale/systemd/backup scripts, and
  their tests. This is a working-tree deletion committed on the branch — it does
  **not** touch `mainline`'s history.
- **Keep / copy the reusable core** — do **not** `git cherry-pick`. Cherry-pick
  replays *commits*, and the reusable code (engine, action registry + specs,
  schemas, temporal, token hashing) is woven through history alongside the
  runtime being discarded — replaying commits would drag that coupling back in.
  Instead, **retain those modules as files** in the working tree (keep the dirs
  when you delete the rest; copy individual files where needed). This is the
  Phase 1b "lift the core" step. File-level selection, not commit replay.

### Lift map — exact source paths (the agent's reference point)
The reusable code lives at these paths on `mainline` (verified against the current
tree). An agent lifting the core copies **from these**, and can read them for
reference even after Session 0 deletes the old runtime on the branch — they remain
in `mainline`'s history and tree until the branch replaces it (see "Reference
point" below).

| Reuse (lift ~as-is) | Source path(s) on `mainline` | Notes |
|---|---|---|
| Engine (registry, `ActionSpec`, `DataType`, dispatch, propose contract, `propose_bounded`) | `app/routing/engine.py` | Already infra-agnostic; the boundary test target |
| Action specs + handlers + registry | `app/assistant/actions/` (`registry.py`, `work_items.py`, `events.py`, `meta.py`, `shared.py`, `context.py`) | Handlers currently take a `Session` via `NtakeActionContext` → **rewrite to the `Repository`** (LLD §2); specs/describe/render_card lift as-is |
| Seam contracts + capture value types | `app/assistant/base.py`, `app/assistant/capture.py` | `CaptureResolver`/`AssistantClient`/`FocusedContext`/`ProposedAction` |
| Tools view/schema projection | `app/assistant/tools_view.py` + the `DataType.json_schema` fragments in `engine.py` | Feeds the §3.3 Anthropic tool `input_schema` translation |
| API DTOs | `app/schemas.py` | ints → ULID strings (LLD §1 ripple) |
| Temporal (UTC ↔ family-local) | `app/persistence/temporal.py` | Pure; lifts clean |
| Token hashing | `app/identity/tokens.py` | HMAC; secret source changes to Secrets Manager (LLD §5.1) |
| Reference tests (patterns to re-use, not run as-is) | `tests/assistant/`, `tests/identity/` | Behavioral contracts to re-express as integration tests over the new seams |

| Rewrite (do NOT lift) | Old path (delete) | Replaced by |
|---|---|---|
| Persistence | `app/persistence/` (SQLAlchemy models, `database.py`, `migrations.py`), `alembic/` | `DynamoRepository` + `InMemoryRepository` (LLD §2) |
| HTTP app | `app/main.py` (FastAPI routes), `app/web.py`, `app/web_shell.py` | thin Lambda handlers (LLD §4/§5) |
| LLM runtime | `app/assistant/local_llm/` (httpx/llamafile) | the two Anthropic-API seams (LLD §3) |
| Live sync | `app/event_emitter.py`, the `register_change_events`/SSE path | WebSocket direct-post (LLD §4) |
| Config/CLI/ops | `app/config.py`, `app/manage.py`, `setup.sh`, backup/Tailscale scripts | CDK + pairing-code enrollment + `scripts/mint.py` bootstrap (LLD §5/§7) |

### Reference point after deletion (important)
Session 0 deletes the old runtime **on the `aws-rebuild` branch**, so an agent
working on the branch can no longer see those files in its working tree. The
reference remains available two ways — tell the agent to use them: (a) **read
`mainline`** for any old file without checking it out — `git -P show
mainline:app/assistant/actions/work_items.py` (or browse the branch in the UI);
(b) the **lifted copies themselves** (the kept core) are the living reference once
in-tree. So "what did the old handler do?" is always answerable via
`git show mainline:<path>` even mid-rebuild. Do the lift (Session 1 / Phase 1b)
**before** or in the same session as any deletion of modules you still need to
read, so nothing needed is only reachable through `git show`.
- **End state (decision):** when the rebuild is done it is intended to **replace**
  `mainline` (the home-PC design is superseded — see HLD framing). "Replace" means
  eventually **merging the branch in as new commits**, *not* rewriting history —
  consistent with the repo's no-force-push / no-rewrite rule. Until then the two
  lines coexist; `mainline` remains the working self-hosted app.

**Why this practice:** it's a clean-room-on-a-branch for a shared-repo rewrite —
you get an AWS-shaped tree uncluttered by the old runtime while still lifting the
tested, infra-agnostic parts, and `mainline` stays a safe, recoverable fallback
the whole time. The only disciplines: keep it a branch (never a `mainline`
rewrite), and select **files**, not commits.

---

## Phase 0 — AWS account foundation (minimal human touchpoints)

**Design goal: the fewest irreducible human actions.** A step is only truly
human when it needs **root authority** or **creates the first credential / a
human-gated opt-in** — everything else is CDK or a one-shot script. That reduces
first-time setup to **two console actions in one sitting, then one script**. After
that, *all* future work (dev + prod deploys, redeploys) is `cdk deploy` from the
CLI — no console, ever.

### The irreducible human minimum — console actions, one session  [HUMAN]
- **0a. Create a non-root admin identity + CLI credentials.** Only the root user
  can bootstrap the first non-root principal, so this one console login is
  unavoidable. Preferred: **IAM Identity Center** user + admin permission set
  (short-lived CLI creds, no static keys); simpler: an **IAM user** +
  `AdministratorAccess` + access keys. **MFA either way.** (Root + MFA is already
  done ✓; don't use root after this.) Pick the region here too (**us-east-1**, the
  pinned region — one config value, pinned in CDK).
- **0b. Obtain an Anthropic API key** (not an AWS console action — done in the
  **Anthropic console**, `console.anthropic.com`). Create a workspace-scoped API
  key for this app; it is the assistant's credential (LINK + PROPOSE). The key is
  **not** set here — it is stored out-of-band into Secrets Manager after the dev
  stack exists, via `make secrets-anthropic` (Phase 5 / Session 4+). *(This
  replaces the original "0b. Enable Bedrock model access" step: Bedrock invocation
  is blocked by an account-level hold on this account, so the seams use the
  Anthropic API instead — HLD decision §10, LLD §3.5. There is **no Bedrock model
  access to enable** for the build target.)*

### Everything else — one script, then CDK  [AGENT provides / HUMAN runs once]
- **0c. Configure the CLI + run `./setup-aws.sh`** (provided in Phase 1): verifies
  `aws sts get-caller-identity` is the **non-root** admin on `111037110464`, then
  runs **`cdk bootstrap`** (one-time per account+region). One command, not console
  clicking.
- **0d. Not a human step — folded into CDK:** the **billing budget + alert** is an
  **AWS Budgets construct deployed with the stack** (Phase 5b), not a console
  action. IAM, Secrets Manager, throttles, lifecycle rules — all CDK.

**Done when:** `aws sts get-caller-identity` shows the non-root admin on
`111037110464`, an **Anthropic API key exists** (stored into Secrets Manager once
the dev stack is up — Session 4+), and `./setup-aws.sh` (bootstrap) succeeds. Net
human effort: **one console session + one script run** (+ obtaining the Anthropic
key in the Anthropic console).

---

## Phase 1 — Project skeleton + CI gate  [AGENT]

Stand up the new `ntake-aws` package shape (HLD §5) and the local quality gate so
every later phase lands against a green build.

- **1a.** New package: `infra/` (CDK), `handlers/`, `adapters/`, `core/` (the
  lifted infra-agnostic modules), `tests/`. Pinned deps; ruff + mypy + test
  runner config.
- **1b.** Lift the infra-agnostic core unchanged: engine (registry, `ActionSpec`,
  dispatch, propose contract), the ntake action specs, schemas, temporal, token
  hashing. **Extend the boundary test** to forbid `boto3`/`fastapi`/persistence
  imports in the engine (the AWS analog of the old sqlalchemy-boundary test).
- **1c.** `cdk synth` of a minimal empty stack passes in CI (infra compiles
  without deploying). Local gate green.
- **1d.** Provide **`setup-aws.sh`** (the Phase 0c one-shot): assert
  `get-caller-identity` is the non-root admin on `111037110464`, then
  `cdk bootstrap aws://111037110464/us-east-1`. Idempotent; safe to re-run.

**Done:** gate green; core lifted + boundary-tested; `cdk synth` clean.

---

## Phase 2 — Data layer: single-table repository  [AGENT]

The DynamoDB single-table design (HLD §6), test-first against an **in-memory fake
repository** (Tier 1) and the **real dev-stage table** via `make integration`
(Tier 2). (No DynamoDB Local — dropped under the two-tier model, 2026-10-02.)

- **2a.** Define the single-table schema: PK/SK, the two GSIs (board =
  status+position sparse key; calendar = unified time sort key), item shapes for
  family / member / device-token / work-item (co-located item + nested log +
  checklist) / event (flat + denormalized provenance) / connections. **ULID** ids.
- **2b.** The **repository interface** (the seat the old `Session` held) + the
  **in-memory fake** (fast Tier-1 unit tests) + the **DynamoDB implementation**
  (boto3, endpoint-/region-configurable; exercised at Tier 2 against the real
  dev table). Owns `UpdateItem` for intra-item writes and `TransactWriteItems`
  for the two cross-item cases (co-created event; reserved spill-truncate).
- **2c.** Port the action handlers to the repository (no `boto3` in handlers).
  Access-pattern tests: board Query, calendar Query, work-item single-`GetItem`
  read, append-to-log, archive = drop GSI key.
- **2d.** S3 log-spill is **designed-for, not built** — the item reserves a
  pointer slot; no spill subsystem. (HLD §6.)

**Done:** repository + both impls green; all action handlers run over the
repository; access patterns verified on the real dev-stage table via
`make integration`.

---

## Phase 3 — Assistant on the Anthropic API: two seams  [AGENT]

LINK + PROPOSE against the **Anthropic Messages API** (HLD §7). Code +
deterministic tests are local (Tier 1, scripted seam, no key, no network);
real-model behavior is validated incrementally in the dev stage (Tier 2) — and,
unlike the Bedrock plan, **this is no longer gated on any AWS authorization**:
the Anthropic key is a Secrets Manager value, so the real-model run is available
as soon as the key is set.

- **3a.** **LINK** = constrained-JSON Messages seam → `{work_item_ids,
  event_ids, member_ids}` → app validates against the family (validate-don't-
  trust) → whitelist. Deterministic first-person linking preserved.
- **3b.** **PROPOSE** = Messages **tool-use** over the registry-as-`tools`;
  `tool_choice: {"type": "any"}` with `no_action` as a tool; ids as
  **enum-over-whitelist** in the tool `input_schema`, **plus app-side whitelist
  re-validation** (defense-in-depth). Returns `tool_use` block(s) → proposal
  cards; **stops** (no `tool_result`, no loop) — execution only on Confirm.
- **3c.** Scriptable Anthropic seams (the `ScriptedLLM` analog, Anthropic-shaped)
  keep LINK/PROPOSE tests deterministic, no network, no key.
- **3d.** **Multi-tool-call — resolved by the pivot (HLD §7 / LLD §3.5):** the
  Anthropic Messages API supports parallel tool use (multiple `tool_use` blocks in
  one response) natively, so the Bedrock-era "one call per turn?" risk is gone. The
  handler consumes a **list** of blocks regardless. Remaining check is prompt
  quality (does Claude actually emit multiple for a multi-intent note) — verified
  against the real model in the dev stage; one-proposal-per-capture is the
  acceptable fallback if it prefers one.

**Done:** both seams built; deterministic tests green; the real-model run wired
into `make integration` (runnable now, not blocked).

---

## Phase 4 — Thin handlers + API + identity  [AGENT]

Wire the HTTP surface and auth (HLD §4, §9). Handlers are thin I/O over the
registry + repository + the Anthropic assistant seams.

- **4a.** REST handlers for the carried-over routes (health, events read,
  work-item/board read, `POST /work-items` create, `POST /work-items/{id}/updates`
  append, `/capture`, `/actions/confirm`) — thin, logic in the core.
- **4b.** The **Lambda custom authorizer**: hash the bearer token (HMAC via a
  secret in **Secrets Manager/SSM**) → member + allow policy. WebSocket `$connect`
  authorizes via `?token=`.
- **4c.** **Device enrollment by pairing code** *(as built in Session 6 —
  replaces the original admin-Lambda mint + `/enroll#token=` URL flow, which the
  owner found cumbersome: it needed the admin account for every device and a
  long token URL copied onto the device).* An already-enrolled member calls
  `POST /pairing-codes` and gets a **6-digit code** (single-use, 10-minute TTL,
  attempt-capped); the new device sends it to the public `POST /pair` and gets
  back a full-entropy device token (only its HMAC hash is stored). The human
  only ever moves 6 digits between devices. **First-device bootstrap** (no
  enrolled adult yet) is `make mint` → `scripts/mint.py`, run once per family
  with AWS creds; it prints a pairing code so bootstrap uses the same flow.
  `revoke` sets `revoked_at`. A deployed admin-mint Lambda is deferred
  (break-glass only).
- **4d.** *(Superseded by 4c.)* The `/enroll#token=` URL/QR receive flow is not
  built; the frontend's enrollment surface is the "enter your pairing code"
  screen (Phase 6c).
- **4e. Publish-at-the-boundary** live sync: right after the repository commits,
  the confirm/execute boundary posts the `{entity,id,op}` nudge to the family's
  WebSocket connections (direct-post, HLD §8). A boundary test guards that **all
  writes flow through this one publish point** (completeness without Streams).

**Done:** API + authorizer + pairing-code enrollment + direct-post live sync
built; handler/auth tests green; the single-publish-boundary invariant is
test-guarded.

---

## Phase 5 — CDK stacks + dev stage integration  [AGENT build / HUMAN deploy]

Everything becomes CDK; the **dev stage** shakes out the cloud-only seams local
testing can't (HLD §11).

- **5a.** CDK stack (**builds on the slices already in `NtakeStack`** — the table
  from Session 3, the APIs/authorizer/Lambdas from Session 6 — not a from-zero
  build): HTTP API, WS API,
  DynamoDB (+ GSIs, TTL), Lambdas, CloudFront, S3 (static assets + **assistant-logs
  bucket w/ 180-day lifecycle rule**, HLD §10), IAM (scoped per-Lambda — capture
  Lambda gets `secretsmanager:GetSecretValue` on the Anthropic-key secret, **no**
  `bedrock:InvokeModel`), authorizer wiring, **two Secrets Manager secrets** (HMAC
  token + Anthropic API key, both created empty — values set out-of-band via
  `make secrets-token` / `make secrets-anthropic`). **Per-stage typed props:** `assistantLogFidelity`
  (default `full`), `anthropicModelId`, throttle limits, removal/retention policy.
  **Billing budget + alert as an AWS Budgets construct** (so cost protection
  deploys with the stack, not a console step — NFR-COST, §2a).
- **5b.** **Assistant call logging → S3** (HLD §10): full-fidelity default,
  per-call JSON object keyed `assistant-logs/<family>/<date>/<ulid>.json`;
  `s3:PutObject` grant on the capture (Anthropic-calling) Lambda.
- **5c.** Deploy the **full `dev`** stack **[HUMAN: `cdk deploy`]** — `DESTROY`
  removal, disposable table, fake data. (First cloud contact + the IAM /
  WebSocket-loop questions were de-risked earlier by the
  **tracer-bullet deploy (Part II, Session 1.5)**; this is the *full-stack*
  integration against the real handlers/repository/seams.) **Re-validate at full
  scale:** IAM across all Lambdas, the **real Anthropic API** with the complete
  tool set (confirm tool-use/enum/multi-tool-call behavior at full tool count,
  Secrets Manager key read + egress to `api.anthropic.com`; prompt quality
  eyeballed), and the full API Gateway → authorizer → WebSocket post-back loop.
- **5d.** API Gateway **throttling/rate limits** (token is now the primary
  internet boundary, HLD §9).

**Done:** full dev stack live; IAM + the Anthropic seam + live-sync validated at
scale; LLD updated if anything changed at full scale.

---

## Phase 6 — Frontend (PWA on CloudFront)  [AGENT build / HUMAN device test]

The PWA served from CloudFront as a very simple static client (HLD §12a, LLD §9).

- **6a.** Serve the static PWA (`index.html` + `app.js` + `app.css` +
  manifest/sw/icon) from **S3 + CloudFront** — hand-written vanilla JS, no
  framework, no build step.
- **6b.** Render from the **JSON APIs** (`/board`, `/events`, `/work-items`,
  `/capture`, `/actions/confirm`); the live-sync client uses `WebSocket`
  (`?token=`, refetch-and-rerender on nudge, reconnect re-sync). The old
  server-rendered fragment routes are not built.
- **6c.** The **enrollment screens** (the 4c pairing flow: "add a device" shows a
  6-digit code with a countdown on an enrolled device; an unenrolled device shows
  "enter your pairing code", calls `POST /pair`, stores the token in
  `localStorage`) + the capture / board / calendar / proposal-card surfaces over
  the authenticated API.
- **6d. [HUMAN]** Install the PWA on phones + the wall tablet; device smoke
  (install, enroll via pairing code, capture→propose→confirm, live update across
  devices).

**Done:** PWA installs and runs against dev; pairing-code enrollment works
end-to-end on a real device; live sync verified across two devices.

---

## Phase 7 — Prod cutover  [AGENT config / HUMAN deploy]

- **7a.** Prod stack props: **`RETAIN` + point-in-time recovery** on the table
  (replaces the old weekly snapshot), tighter throttles, the chosen Claude model,
  `assistantLogFidelity` as desired.
- **7b. [HUMAN]** Deploy **`prod`**; set the prod secrets
  (`make secrets-anthropic STAGE=prod`, `make secrets-token STAGE=prod`);
  bootstrap the first device per family (`make mint`), then enroll the rest via
  pairing codes.
- **7c. [HUMAN]** Bootstrap-minting hardening follow-on (IP allowlist / second
  factor, if a deployed minting path is ever added — HLD §9) — tracked, not
  blocking initial prod.
- **7d. [HUMAN]** Kiosk soak on the wall tablet.

**Done:** prod live on `111037110464`; data protected by PITR; real devices
enrolled.

---

## Deferred / not in this plan (unchanged from HLD §1, §6, §13)
- S3 log-spill subsystem (designed-for, not built).
- DynamoDB Streams completeness upgrade (direct-post is v1; Streams is the
  documented hardening path).
- `.ics` interop, labor view, Trello/Google backfill.
- Cognito (device tokens retained).
- Separate dev/prod **accounts** (one account, two stages).
- CI/CD pipeline (one-command `cdk deploy` per stage to start).

---

## Definition of done for a checkpoint
Code + tests written; local gate (ruff + mypy + tests) clean (output shown);
only in-scope files changed; deps pinned if added; **[HUMAN]** steps called out
explicitly (an agent stops and asks rather than touching the AWS console with the
owner's credentials). Report files changed + gate output + anything uncertain.

---

# Part II — Step-by-step guide for LLM agent sessions

This section turns the phases above into **bounded sessions** an agent runs one at
a time. Each session is sized to fit a single working context, ends at a green
gate, and leaves `main` of the rebuild branch deployable-in-principle. Do **one
session per sitting**; stop at its exit criteria and report.

The flow is **two-tier** (operating-model change, 2026-10-02 — supersedes the
original "local-first for everything, cloud only at Sessions 5/8"):

- **Tier 1 — local/fast (the default gate, `make check`).** ruff + mypy + the
  unit/contract suite against the **in-memory repository** + **scripted Anthropic
  seam**. **No Docker, no DynamoDB Local, no AWS, no credentials, no heavy deps.**
  Always green offline on any machine — this is every TDD inner loop and what a
  fresh agent context runs. Fast, free, flake-free.
- **Tier 2 — remote/integration (`make integration`), built up incrementally.**
  Runs the **same** protocol-level flow/access-pattern tests against the **real
  dev stage** (real DynamoDB now; the real Anthropic API + API GW + WebSocket as
  those land) — and can **deploy** first. Each feature session from Session 3 on
  ships its **code + its infra slice (into `NtakeStack`) + its dev integration**,
  so the dev stage grows gradually alongside the app rather than being deferred to
  one big-bang integration at the end. `make integration` needs AWS credentials
  and is a **[HUMAN]-invoked** step (it self-checks `sts get-caller-identity` and
  stops with configure instructions if creds are missing — it never silently
  skips).

**Why the change:** continuous dev-stage integration front-loads the cloud-only
risks (IAM, real DynamoDB semantics, the Anthropic seam) session-by-session
instead of stacking untested assumptions into Sessions 5/8. Tier 1 keeps the inner
loop fast and portable; Tier 2 proves each slice against real AWS as it is built.
The Session 1.5 tracer-bullet was the first taste of this (it caught the Bedrock
account-auth block early — which is what drove the pivot to the Anthropic API,
HLD §10); the two-tier model generalizes that shift-left to every session.
DynamoDB Local is **dropped** entirely (YAGNI — Tier 1 is in-memory, Tier 2 is the
real table).

## Operating rules (every session)

- **TDD, integration-first.** For each unit of functionality, **write the test
  first**, watch it fail, then write code to pass it. **Prefer integration tests
  that exercise a whole interface/flow** (e.g. a capture→propose round trip
  through the real registry + in-memory repo + scripted Anthropic seam; a repository
  method against the real dev-stage table via `make integration`) **over**
  mock-heavy per-function tests — *supplement* with unit tests for specific pure
  functions (temporal math, schema translation, key composition). The goal: tests
  assert behavior at the seam, not implementation detail, so refactors don't break
  them. The **same** flow tests run both tiers: Tier 1 against the in-memory repo,
  Tier 2 against the real dev table (endpoint-agnostic by construction).
- **DRY + good practice.** One source of truth (the registry drives tools view +
  schema; `DataType` drives param rendering + JSON Schema; the repository is the
  only place table keys live). No copy-paste handlers; factor shared helpers.
  Match the existing code's style and typing discipline (full type hints, no
  `Any`, the engine boundary).
- **YAGNI (You Aren't Gonna Need It).** Build only what the session's scope
  names. Don't add speculative config, defensive branches, abstractions, or
  "might need it later" knobs — unused surface area is cost (later sessions must
  read, test, and maintain it), not safety. If something genuinely seems needed
  beyond scope, record it as a to-verify/deferred note rather than building it.
  (Session 1.5 learned this twice: a dual-shape authorizer and a speculative
  `inferenceConfig`, both built then removed once they proved unnecessary.)
- **Lambda code is stdlib + the runtime's `boto3` only — no dependency
  bundling** *(decided in Session 6 after the first deploy 500'd)*. The CDK
  Lambda asset is our source as-is; the Python 3.12 Lambda runtime provides
  `boto3` (and its deps) and no other third-party package. So `core/`,
  `adapters/` and `handlers/` must not import anything else — the DTOs are
  stdlib dataclasses (`core/schemas.py`) serialized by `core/serde.py`, not
  Pydantic. Guarded at Tier 1 by `tests/test_lambda_runtime_deps.py` (imports
  every Lambda entry module in a clean interpreter and fails on any
  non-runtime import). Adding a third-party runtime dependency is a deliberate
  design change (it brings a bundling step), not a casual import.
- **No env-var switches for build/test behavior.** Don't add environment flags
  to toggle how the stack synthesizes or how tests run (e.g. a
  "skip bundling" flag). CDK-set Lambda runtime config (table name, secret ids)
  is the one legitimate deploy-time env use (LLD §6).
- **The gate is mandatory before a session is "done":** run `make check` (Tier 1
  — local/fast, the TDD inner loop) and paste real output. Never claim green
  without running it.
- **Tier 2 is a per-session gate, not an afterthought (every feature session,
  Session 3 on).** Each session must **wire** its `make integration` path — the
  dev-stage integration for the slice it built — and **run it to close the
  session**. `make integration` is **[HUMAN]-invoked** (the agent builds + surfaces
  the command/results; the human runs anything that writes the account). The
  target **self-checks its preconditions and stops cleanly with a clear
  message**, treating an unmet precondition as a recorded **[HUMAN]** follow-up —
  it **never silently skips and never fakes a pass**:
  - **credentials** — via `aws sts get-caller-identity` (missing/wrong-account →
    stop with configure instructions);
  - **model-dependent slices (LINK/PROPOSE/capture, Sessions 4–8)** — an
    **Anthropic-key self-check**: the real-model run calls the Anthropic Messages
    API with the key from Secrets Manager (`ntake-dev/anthropic-api-key`). The
    integration path checks the secret has a value (and, locally, that
    `ANTHROPIC_API_KEY` is set for a direct run); if absent, it **stops cleanly**
    ("Anthropic key not set — run `make secrets-anthropic` / export
    `ANTHROPIC_API_KEY`"), exactly like the `sts` guard. **Unlike the Bedrock
    plan, there is no AWS-side authorization gate** — the key is the only
    precondition, and it is already in place, so the real-model run is **runnable
    now**, not deferred. The agent builds the real Tier-2 path and runs it to close
    the session.
  So an unmet precondition (missing creds or key) is handled by a wired,
  self-checking Tier-2 path that stops cleanly — not by dropping the Tier-2 gate or
  claiming Tier-1-only. (Same never-silently-skip discipline as the `sts`
  self-check and the current `SKILL.md`.)
- **Tooling is `make` + `scripts/`** (see "Tooling to build" below) — agents use
  targets, not raw commands.
- **Scope + honesty.** Change only what the session names. If blocked, stop and
  report the full error (don't loop). **[HUMAN]** steps: stop and ask; never touch
  the AWS console/credentials unprompted. `make integration` (deploy + run against
  the real dev stage) is **[HUMAN]-invoked** — the agent writes it, surfaces the
  command + results, and the human runs anything that deploys to or writes the
  account. The target self-checks `aws sts get-caller-identity` and stops with
  configure instructions if creds are missing or wrong-account.
- **Branch:** all sessions run on the `aws-rebuild` branch (see Git strategy).
  Commit at each green gate with a conventional-commit message.

## Tooling to build (Session 1 establishes it; later sessions extend it)

Mirror the current repo's thin-launcher pattern — a `Makefile` delegating to
`scripts/` and the venv binaries. Target set for the AWS app:

| Target | Does |
|---|---|
| `make setup` | venv + install pinned deps + verify (delegates to `setup.sh`) |
| `make test` | full **Tier 1** pytest suite (unit + in-memory integration; no cloud) |
| `make test-core` / `-data` / `-assistant` / `-api` / `-infra` | focused Tier-1 suites per Part-I phase |
| `make lint` / `format` | ruff check(+format-check) / ruff auto-fix |
| `make typecheck` | mypy |
| `make check` | **Tier 1 gate: lint + typecheck + coverage-enforced in-memory tests** (no cloud) |
| `make synth` | `cdk synth` (infra compiles, no deploy) |
| `make integration` | **Tier 2: run the integration suite against the real dev stage.** Self-checks `aws sts get-caller-identity` (stops with configure instructions if creds missing/wrong-account). `make integration DEPLOY=1` **deploys first** (`cdk deploy NtakeStack-dev`) then tests; without the arg it tests whatever is already deployed. **[HUMAN]-invoked** (needs creds). Grows each session as infra slices land. |
| `make deploy-dev` / `deploy-prod` | `cdk deploy` the stage (human-initiated; `deploy-dev` is also what `integration DEPLOY=1` calls) |
| `make secrets-anthropic` | **[HUMAN]** set/rotate the Anthropic API key into Secrets Manager (`ntake-<stage>/anthropic-api-key`); `STAGE=dev\|prod`. Key read from `$ANTHROPIC_API_KEY` or a silent prompt — never passed as an argument. Run after the stage is deployed (CDK creates the empty secret). |
| `make secrets-token` | **[HUMAN]** set/rotate the HMAC device-token secret (`ntake-<stage>/token-secret`) with a freshly generated random value. Run after the stage is deployed (CDK creates the empty secret). Rotating invalidates every existing device token. |
| `make mint` | **[HUMAN]** first-device bootstrap for a family: `FAMILY=… MEMBER=…` → prints a 6-digit pairing code (`scripts/mint.py`; `MINT_ARGS=--token` mints a token directly). |
| `make dev-reset` | **[HUMAN]** `cdk destroy NtakeStack-dev` (drops the dev table + data) for a clean slate; recreate with `make integration DEPLOY=1`. Never touches prod. |

`make integration` also accepts `PYTEST_ARGS` (e.g. `PYTEST_ARGS='-s'` to see the
live LLM request/response prints from the pipeline tests).

Scripts under `scripts/`: `setup.sh` (venv+install+verify), `setup-aws.sh`
(assert non-root admin on `111037110464` + `cdk bootstrap us-east-1`),
`integration.sh` (the `sts` self-check + optional `cdk deploy` + run the Tier-2
suite), `secrets-anthropic.sh` / `secrets-token.sh` (set/rotate the two secrets,
value-safe), and `mint.py` (first-device bootstrap).
Keep each thin and single-purpose (DRY: `make` calls scripts, scripts
don't duplicate `make`). **Dropped (YAGNI, 2026-10-02):** `ddb_local.sh` /
`make ddb-up` / `ddb-down` (no DynamoDB Local — Tier 1 is in-memory, Tier 2 is the
real table) and the standalone `bedrock_smoke.py` / `make bedrock-smoke` (the real
Anthropic-seam check is part of `make integration` once the capture path's infra
slice lands).

> **Bedrock probe scripts — deleted** with the tracer teardown (after Session 5).
> `bedrock_preflight.py` / `bedrock_bisect.py` / `make bedrock-preflight` no
> longer exist; the build target is the Anthropic API. Recover them from git
> history if the Bedrock fallback is ever revisited (LLD §3.5).

---

## Session 0 — Branch + account preflight  [HUMAN-assisted]
**Goal:** the rebuild branch exists and the account is ready.
- **[HUMAN]** the two console actions (Phase 0a/0b) + `setup-aws.sh` (0c).
- **[AGENT]** create the `aws-rebuild` branch; **first lift the reusable core**
  into its new home (per the **Lift map** in the Git-strategy section), **then**
  `git rm` the home-PC runtime. Order matters: lift before (or in the same commit
  as) deletion so nothing you still need is only reachable via
  `git show mainline:<path>`. Commit.
**Exit:** branch exists, old runtime removed, core files retained, account
bootstrapped (`aws sts get-caller-identity` = non-root admin; `cdk bootstrap` ok).

## Session 1 — Skeleton + gate + test harness + tooling  (Phase 1)
**Goal:** green `make check` on an empty-but-wired project, **with the shared test
harness in place** so every later session reuses it instead of re-inventing
fixtures.
- TDD-first is light here (scaffolding): stand up the package shape, `Makefile`,
  `scripts/`, pinned deps, ruff/mypy/pytest config.
- Lift the infra-agnostic **core** (engine, action specs, schemas, temporal,
  hashing); write the **boundary test** (no `boto3`/`fastapi`/persistence in the
  engine) — that test is real functionality, write it first and make it pass.
- **Establish the test harness (the DRY backbone — LLD §8):** the
  parametrize-over-both-repos fixture (one test body runs against
  `InMemoryRepository` now and `DynamoRepository` later), the **scripted
  assistant-client double** (canned LINK JSON + tool-use blocks), the DynamoDB
  Local wiring (`make ddb-up/down`, skipped-if-absent), and the boundary-test
  tooling. Put these in `tests/conftest.py` + a `tests/harness/` so Sessions 2–9
  import, not re-build. *(Historical: the DynamoDB-Local wiring + the
  backend-parametrized fixture were built here, then **removed in Session 3** when
  the two-tier model dropped DynamoDB Local — see the 2026-10-02 decision note in
  `AWS_PROGRESS.md`. The double shipped as a Converse-shaped `ScriptedBedrockClient`;
  **Session 4 re-homes it as the Anthropic-shaped `ScriptedAnthropicClient`** under
  the provider pivot — LLD §3.4 — since no real Bedrock adapter was ever written.)*
- `make synth` on a minimal empty CDK stack (TS CDK) passes.
**Exit:** `make check` green; boundary test green; the shared harness exists and
is documented; `make synth` clean. Commit.

## Session 1.5 — Tracer-bullet dev deploy (de-risk the cloud-only assumptions early)  [HUMAN deploy]
> **Historical (done). This session's Bedrock finding drove the pivot.** The
> tracer proved IAM ✓ and WebSocket connect/routing ✓, but found **Bedrock
> invocation blocked by an account-level hold** — which is why the assistant seams
> moved to the **Anthropic API** (HLD §10, LLD §3.5). The "real Bedrock tool-use"
> goal below is the record of what it *tried*; the actual build target for
> Sessions 4–5 is the Anthropic Messages API, and the multi-tool-call question is
> resolved by the pivot (parallel tool use is native). Read this as history, not
> as instructions for a fresh session.

**Goal:** prove the three truths local tests *cannot* — **IAM**, **real Bedrock
tool-use**, and the **API-GW → authorizer → WebSocket post-back** loop — with a
minimal throwaway slice, **before** Sessions 2–7 build on those assumptions. This
is a *walking skeleton*, not the real handlers.
- **Minimal CDK slice:** a trivial table, one Lambda behind the HTTP API, the
  authorizer, a WebSocket `$connect`/`$disconnect` + one hard-coded post-back, and
  the Secrets Manager secret. Scaffolding only — deleted/replaced as the real
  sessions land.
- **[HUMAN]** `make deploy-dev` (first deploy).
- **[AGENT]** validate end-to-end against the deployed slice:
  - **IAM** — the Lambda's scoped role actually works (no `AccessDenied`).
  - **Bedrock** — one **real Converse tool-use** call with a hand-written 2-tool
    `toolConfig`: confirm response shape, **whether one turn returns multiple
    `toolUse` blocks (§3.5)**, and **enum-over-whitelist adherence**. This is the
    load-bearing unverified assumption — resolve it here.
  - **WebSocket** — connect (token `?token=`), receive a hard-coded post-back.
- **Feed findings back into the LLD** (§3.5 especially): if the model returns one
  tool call per turn, record the loop/one-proposal fallback decision **now**, so
  Sessions 4–5 build the confirmed shape rather than a hopeful one.
**Exit:** the three cloud seams proven on dev; the multi-tool-call + enum
questions **answered** and written into the LLD; the throwaway slice is clearly
marked scaffolding. Commit. *(Session 1.5 was the first taste of the two-tier
model — the later sessions generalize its shift-left: a fast local Tier-1 gate
plus an incremental Tier-2 `make integration` against the growing dev stack.)*

## Session 2 — Data layer: repository contract + in-memory impl  (Phase 2a/2b-part)
**Goal:** the `Repository` protocol + `InMemoryRepository`, driven by tests.
- **Integration-first:** write tests that drive the repository through whole
  flows (create work item → append update → read back the aggregate; put event →
  list calendar range; board grouping/ordering). Write them against the
  `Repository` protocol so they'll later run **unchanged** against the Dynamo impl.
- Implement `InMemoryRepository` to pass them. Unit-test the pure bits (key/sort
  derivation helpers, `sort_ts` computation) directly.
**Exit:** repository protocol + in-memory impl green under `make test-data`; the
flow tests are impl-agnostic. Commit.

## Session 3 — Data layer: DynamoDB impl + first dev-stage integration slice  (Phase 2b/2c/2d + a slice of 5a)
**Goal:** the same Session-2 flow tests pass against **real DynamoDB** (dev
stage), the action handlers run over the repository, and `make integration` is
established as the Tier-2 harness. This is the **first session under the two-tier
model** — it ships code **+** its infra slice **+** its dev integration.
- **Infra slice (into `NtakeStack`, not the tracer):** add the **real single
  table** `ntake-<stage>` — PK/SK, GSI1 (board, sparse), GSI2 (calendar), TTL attr
  reserved — with per-stage props (dev `DESTROY`). This is the Session-5a table
  slice pulled forward so there is a real table to integrate against. `make synth`
  stays clean.
- **`DynamoRepository`:** boto3 over the single table, implementing the full
  `Repository` protocol, **reusing the pure key/sort helpers in
  `core/repository.py`** byte-for-byte (the single source of table-key knowledge —
  do not re-derive keys). Owns the sparse-GSI write rules and the two
  `TransactWriteItems` (co-created event; standalone stays a single `Put`). The
  boto3 client is **endpoint-/region-configurable** so the same code the Tier-1
  tests exercise in-memory is what Tier-2 runs against the real table.
- **Tier 1 (local, no change to speed):** the Session-2 flow tests keep running
  against `InMemoryRepository` under `make check`.
- **Tier 2 (`make integration`):** wire the Tier-2 harness — `sts` self-check,
  optional `DEPLOY=1` (`cdk deploy NtakeStack-dev`), then run the **same**
  protocol-level flow tests **plus** Dynamo access-pattern tests (sparse-GSI1
  archive drop-out, calendar range Query on GSI2, the co-created-event
  `TransactWriteItems`, assert standalone create is a single `Put`) against the
  **real `ntake-dev` table**. **Drop the DynamoDB-Local harness** (`ddb_local.sh`,
  `make ddb-up/down`, the `requires_dynamodb_local` marker, the skipped `dynamo`
  fixture param) — YAGNI under the two-tier model.
- Port the action handlers to the repository (no `boto3` in handlers — the
  boundary test now covers the actions package too), bringing the six parked
  modules back under the Tier-1 gate (shrink the `pyproject.toml` exclude/omit
  lists + remove the ⚠️ PARKED banners as each returns).
**Exit:** `make check` (Tier 1) green — handlers run over the repo, parked modules
back under the gate, boundary test extended to actions. `make integration` (Tier
2) green against the real `ntake-dev` table — **[HUMAN]-invoked**; if creds are
unavailable this sitting, land the code + the `make integration` wiring with Tier
1 green and record the dev-integration run as a [HUMAN] follow-up (don't fake it).
`make synth` clean (real table slice added to `NtakeStack`). Commit.

## Session 4 — Assistant: LINK + the scriptable seam  (Phase 3a/3c)
**Goal:** grounding works deterministically with no network; the real-model LINK
call runs against the Anthropic API in Tier 2 (no AWS authorization gate).
- **Integration-first:** test the LINK flow end to end — world view in →
  scripted Anthropic JSON out → validate-against-family → resolved whitelist →
  deep-context (over the in-memory repo). Include malformed-reply → degrade.
- Build the **`AnthropicClient` protocol** + the **scripted double**
  (re-home the Session-1 Converse-shaped `ScriptedBedrockClient` to the
  Anthropic Messages shape — top-level `content` list; `{"type":"tool_use",...}`
  blocks; `stop_reason` — LLD §3.4). Implement the LINK call shape (constrained
  JSON via the Messages API; see LLD §3.1 for the forced-tool-vs-prompt choice).
- The **real** `AnthropicClient` (the `anthropic` SDK or a thin `requests`/`urllib`
  Messages call) reads the API key from Secrets Manager (`ntake-dev/anthropic-api-key`)
  at cold start, or from `ANTHROPIC_API_KEY` for a direct Tier-2 run. **Keep the
  key out of logs/traces; fail closed on a missing/invalid key** (don't degrade in
  a way that hides a misconfig). No `bedrock-runtime` anywhere.
**Exit:** LINK flow tests green at Tier 1 (incl. first-person linking, degrade);
`make check` green (real output pasted). **Tier 2:** extend `make integration` to
run one **real LINK call against the Anthropic API** and confirm the
constrained-JSON shape — **runnable now** (the key is set via
`make secrets-anthropic`; no support-case gate). **[HUMAN]-invoked**; if the key
isn't set this sitting, the path stops cleanly and the run is a recorded [HUMAN]
follow-up (don't fake it). Commit.

## Session 5 — Assistant: PROPOSE tool-use + schema translation  (Phase 3b/3d)
**Goal:** registry→`tools`, selection-not-execution, enum-over-whitelist.
- **Unit:** `ActionSpec.params`/`DataType` → tool `input_schema` translation
  (pure); the per-request id-enum overlay.
- **Integration:** focused-context in → scripted `tool_use` block(s) out →
  `ProposedAction` cards; assert **no execution** happens (nothing written), ids
  re-validated against the whitelist, `no_action` handled, and **multiple
  `tool_use` blocks → multiple cards** (the handler consumes a list; the Messages
  API supports parallel tool use natively — §3.5).
- **Port the BUG-001..008 hardening regression suite** (reference:
  `git show main:tests/assistant/test_local_llm_hardening.py`): the validated
  PROPOSE-stage drops — missing/empty required param dropped; timed action missing
  a required time dropped; **BUG-002** explicit-local-weekday/time validation
  (keep a well-formed local time; drop a UTC-suffixed / wrong-shape value rather
  than exposing it as a proposal); a valid call survives alongside an invalid one;
  graceful-degrade (malformed model reply → no proposals, never raises). These
  pin behavior the self-hosted app already validated; re-express them against the
  Anthropic scripted double. (Deferred here from Session 4 — they exercise
  `propose()`, which Session 5 builds.)
**Exit:** PROPOSE flow + translation + hardening tests green at Tier 1; `make check`
green. **Tier 2:** extend `make integration` to run the **real PROPOSE tool-use
call against the Anthropic API** and confirm enum-over-whitelist + the
multi-tool-call behavior (§3.5) at the current tool count — reconciled at full tool
count once all actions are registered. Runnable now (key set; no Bedrock gate); if
the key isn't set this sitting, record as the [HUMAN] follow-up. Commit.

## Session 6 — Thin handlers + authorizer + confirm/execute + live-sync publish  (Phase 4)
**Goal:** the HTTP/auth surface and the execute→publish boundary.
- **Integration-first:** drive each route through its thin handler over the
  in-memory repo + scripted Anthropic seam: health, events read, work-item/board
  read, `POST /work-items` + `POST /work-items/{id}/updates` (direct writes),
  `/capture` (propose-only, writes nothing), `/actions/confirm` (executes via the
  registry, writes via repo, **publishes once**). Assert the
  **single-publish-boundary invariant** test (§4.3).
- Authorizer: HMAC hash → member/allow (unit for hashing; integration for the
  authorizer→handler context pass). Enrollment via the **pairing-code exchange**
  (Phase 4c) — `POST /pairing-codes` + public `POST /pair` + `scripts/mint.py`
  bootstrap — *replacing* the original admin-mint + `/enroll#token=` design.
- **Infra slice:** add the HTTP API + authorizer + WebSocket API + the per-Lambda
  roles for these handlers into `NtakeStack` (building on the Session-3 table
  slice). One Lambda per IAM role; Lambda code is stdlib + runtime `boto3` only
  (no bundling — see Operating rules). `make synth` stays clean.
**Exit:** route + auth + publish-boundary tests green at Tier 1; `make check`
green. **Tier 2:** extend `make integration` so the deployed dev stack serves the
real routes through the real authorizer, and the confirm→execute→publish path
posts a live WebSocket nudge (the server→client delivery deferred from the tracer,
LLD §4.2). Commit.

## Session 7 — Complete the stack: logging + CloudFront/S3 + Budgets + prod props  (Phase 5a/5b)
**Goal:** finish `NtakeStack` (the table + API/authorizer/WS slices already landed
in Sessions 3/6) with the remaining resources, correctly scoped; logging adapter
done.
- **Infra:** add CloudFront + the two S3 buckets (static assets via OAC; the
  assistant-logs bucket w/ 180-day lifecycle), the AWS Budgets construct, the
  Secrets Manager secrets (HMAC token + Anthropic key, if not already from earlier
  slices), and finalize per-stage prop differences (dev `DESTROY`/no-PITR vs prod
  `RETAIN`/PITR, throttles, `anthropicModelId`, `assistantLogFidelity`).
- **Infra tests:** `cdk synth` + template assertions — per-Lambda IAM scoping
  (`secretsmanager:GetSecretValue` on the Anthropic-key secret only on capture —
  **no** `bedrock:InvokeModel`; `s3:PutObject` only on logging; table grants per
  handler), the two GSIs, the logs-bucket lifecycle rule, the Budgets construct,
  dev-vs-prod prop differences.
- Assistant-logging adapter → S3 (full|metadata fidelity), unit-tested on object
  shape + fidelity switch.
**Exit:** `make synth` + infra assertions green; `make check` green. **Tier 2:**
`make integration DEPLOY=1` deploys the now-complete dev stack and the integration
suite still passes end to end. Commit.

## Session 8 — Full-stack dev integration sweep  (Phase 5c/5d)  [HUMAN deploy]
**Goal:** a final, whole-stack `make integration` pass on dev — reconciling the
per-session slices into one end-to-end run. (Under the two-tier model, cloud
integration already happened **incrementally** in Sessions 3/6/7; this is the
consolidation sweep + the full-tool-count Anthropic reconciliation, not first cloud
contact.)
- **[HUMAN]** `make integration DEPLOY=1` (deploy the complete dev stack, then run
  the whole Tier-2 suite).
- **[AGENT]** confirm the real capture→propose→confirm flow end to end against the
  **real Anthropic API** + real DynamoDB + the real authorizer and WebSocket
  post-back on the deployed dev stack (disposable data). Reconcile the §3.5
  findings at the **full tool count** (the complete registry, not the per-session
  subset): enum adherence across all id-bearing actions and the multi-tool-call
  behavior.
- Any divergence surfaced at full scale is recorded; the §3.5 fallback is already
  wired, so adjust the call-count, no reshape.
**Exit:** the full stack validated on dev in one sweep; §3.5 reconciled at full
tool count; LLD updated if anything changed at scale. Commit.

## Session 9 — Frontend (very simple static PWA on CloudFront)  (Phase 6)  [HUMAN device test]
**Goal:** the installable static PWA against dev, WebSocket live sync,
pairing-code enrollment (LLD §5.4, §9).
- Build the **very simple hand-written vanilla-JS PWA — no framework, no build
  step** (`index.html` + `app.js` + `app.css` + manifest/sw/icon), served static
  from S3+CloudFront. It **renders from the JSON APIs** (`/board`, `/events`,
  `/work-items`, `/capture`, `/actions/confirm`); the old server-rendered
  `/board/view` / `/calendar/view` fragments are **not** built.
- Live sync: open the `WebSocket` (`?token=`), refetch-and-rerender on a nudge,
  reconnect re-sync on open. The pairing-code screens ("add a device" code
  display; "enter your pairing code"). Capture / board / calendar /
  proposal-card surfaces.
- Integration-test the testable units (the pairing exchange + token storage; the
  WS-nudge→refetch logic) — minimal, matching the simple-client scope.
- **[HUMAN]** install on phone + tablet; device smoke (enroll via pairing code,
  capture→propose→confirm, cross-device live update).
**Exit:** PWA runs against dev; pairing-code enrollment works on a real device;
live sync across two devices. Commit.

## Session 10 — Prod cutover  (Phase 7)  [HUMAN deploy]
**Goal:** prod live, data protected.
- **[AGENT]** finalize prod props (RETAIN+PITR, throttles, model).
- **[HUMAN]** `make deploy-prod`; set the prod secrets; bootstrap the first
  device per family (`make mint`) and enroll the rest via pairing codes; kiosk
  soak. Bootstrap-minting hardening tracked as follow-on.
**Exit:** prod live on `111037110464`; PITR on; real devices enrolled.

## Session 11 — Replace mainline  (Git strategy end-state)
**Goal:** the AWS build becomes `mainline`.
- **[HUMAN/AGENT]** merge `aws-rebuild` into `mainline` **as new commits** (never
  a force-push/rewrite — repo rule). Update `README.md` to describe the AWS app as
  current; the self-hosted docs/history remain recoverable in history.
**Exit:** `mainline` is the AWS app; old app preserved in history.

---

## Session hand-off note (write this at the end of every session)
Each session ends by appending a short note (in the CR/commit body or a scratch
`spec/AWS_PROGRESS.md`): what landed, the `make check` output summary, any
to-verify items opened/closed, and the exact next session to run. This lets a
fresh agent context resume without re-deriving state.
