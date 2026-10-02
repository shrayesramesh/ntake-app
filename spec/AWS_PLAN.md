# Family Calendar + Work Items on AWS — Build Plan

> The phased plan for the **from-scratch AWS-native rebuild**. Architecture is in
> [`AWS_HLD.md`](AWS_HLD.md); detailed design will be in the forthcoming AWS LLD.
> This supersedes the self-hosted `PLAN.md` for the AWS effort — `PLAN.md`
> describes the old home-PC build and is **not** the plan for this work.
>
> **Method:** TDD — tests first; the local gate (ruff + mypy + the test suite)
> must be clean before a checkpoint is done. Rule carried over from the original:
> **TDD the code you own; smoke-test the environment you don't** (here: AWS
> services — IAM, Bedrock, API Gateway — are validated in the cloud **dev stage**,
> not asserted locally).
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
(pinned — Bedrock-capable; used by the setup script and CDK config).

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
| Tools view/schema projection | `app/assistant/tools_view.py` + the `DataType.json_schema` fragments in `engine.py` | Feeds the §3.3 `toolConfig` translation |
| API DTOs | `app/schemas.py` | ints → ULID strings (LLD §1 ripple) |
| Temporal (UTC ↔ family-local) | `app/persistence/temporal.py` | Pure; lifts clean |
| Token hashing | `app/identity/tokens.py` | HMAC; secret source changes to Secrets Manager (LLD §5.1) |
| Reference tests (patterns to re-use, not run as-is) | `tests/assistant/`, `tests/identity/` | Behavioral contracts to re-express as integration tests over the new seams |

| Rewrite (do NOT lift) | Old path (delete) | Replaced by |
|---|---|---|
| Persistence | `app/persistence/` (SQLAlchemy models, `database.py`, `migrations.py`), `alembic/` | `DynamoRepository` + `InMemoryRepository` (LLD §2) |
| HTTP app | `app/main.py` (FastAPI routes), `app/web.py`, `app/web_shell.py` | thin Lambda handlers (LLD §4/§5) |
| LLM runtime | `app/assistant/local_llm/` (httpx/llamafile) | the two Bedrock seams (LLD §3) |
| Live sync | `app/event_emitter.py`, the `register_change_events`/SSE path | WebSocket direct-post (LLD §4) |
| Config/CLI/ops | `app/config.py`, `app/manage.py`, `setup.sh`, backup/Tailscale scripts | CDK + minting admin path (LLD §5/§7) |

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

### The irreducible human minimum — two console actions, one session  [HUMAN]
AWS gates exactly two things behind a human in the console; do them in one login:
- **0a. Create a non-root admin identity + CLI credentials.** Only the root user
  can bootstrap the first non-root principal, so this one console login is
  unavoidable. Preferred: **IAM Identity Center** user + admin permission set
  (short-lived CLI creds, no static keys); simpler: an **IAM user** +
  `AdministratorAccess` + access keys. **MFA either way.** (Root + MFA is already
  done ✓; don't use root after this.)
- **0b. Enable Bedrock model access** (same console session). Bedrock → **Model
  access** → enable the Claude/Nova model in the target region. This is a
  one-time, account-level, human-gated opt-in (a usage acknowledgment) that **CDK
  cannot grant** — without it, Converse fails even with correct IAM. Pick the
  region here too (**us-east-1**, the pinned region — Bedrock-capable);
  it's one config value, pinned in CDK.

### Everything else — one script, then CDK  [AGENT provides / HUMAN runs once]
- **0c. Configure the CLI + run `./setup-aws.sh`** (provided in Phase 1): verifies
  `aws sts get-caller-identity` is the **non-root** admin on `111037110464`, then
  runs **`cdk bootstrap`** (one-time per account+region). One command, not console
  clicking.
- **0d. Not a human step — folded into CDK:** the **billing budget + alert** is an
  **AWS Budgets construct deployed with the stack** (Phase 5b), not a console
  action. IAM, Secrets Manager, throttles, lifecycle rules — all CDK.

**Done when:** `aws sts get-caller-identity` shows the non-root admin on
`111037110464`, Bedrock model access is enabled in the region, and
`./setup-aws.sh` (bootstrap) succeeds. Net human effort: **one console session +
one script run.**

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

The DynamoDB single-table design (HLD §6), test-first against **DynamoDB Local**
and an **in-memory fake repository**.

- **2a.** Define the single-table schema: PK/SK, the two GSIs (board =
  status+position sparse key; calendar = unified time sort key), item shapes for
  family / member / device-token / work-item (co-located item + nested log +
  checklist) / event (flat + denormalized provenance) / connections. **ULID** ids.
- **2b.** The **repository interface** (the seat the old `Session` held) + the
  **in-memory fake** (fast unit tests) + the **DynamoDB implementation**
  (DynamoDB Local). Owns `UpdateItem` for intra-item writes and
  `TransactWriteItems` for the two cross-item cases (co-created event; reserved
  spill-truncate).
- **2c.** Port the action handlers to the repository (no `boto3` in handlers).
  Access-pattern tests: board Query, calendar Query, work-item single-`GetItem`
  read, append-to-log, archive = drop GSI key.
- **2d.** S3 log-spill is **designed-for, not built** — the item reserves a
  pointer slot; no spill subsystem. (HLD §6.)

**Done:** repository + both impls green; all action handlers run over the
repository; access patterns verified on DynamoDB Local.

---

## Phase 3 — Assistant on Bedrock: two seams  [AGENT] (+ [HUMAN] model access)

LINK + PROPOSE against Bedrock (HLD §7). Code + deterministic tests are local;
real-model behavior is validated in Phase 5 (dev stage).

- **3a.** **LINK** = constrained-JSON Converse seam → `{work_item_ids,
  event_ids, member_ids}` → app validates against the family (validate-don't-
  trust) → whitelist. Deterministic first-person linking preserved.
- **3b.** **PROPOSE** = Converse **tool-use** over the registry-as-`toolConfig`;
  `toolChoice: "any"` with `no_action` as a tool; ids as **enum-over-whitelist**
  in the tool `inputSchema`, **plus app-side whitelist re-validation**
  (defense-in-depth). Returns tool-use block(s) → proposal cards; **stops** (no
  `toolResult`, no loop) — execution only on Confirm.
- **3c.** Scriptable Bedrock seams (the `ScriptedLLM` analog) keep LINK/PROPOSE
  tests deterministic, no network.
- **3d.** **Resolve the to-verify:** does one Converse turn return **multiple
  tool-use blocks**? Verify against the real model in Phase 5; if not, fall back
  to loop-PROPOSE or one-proposal-per-capture (HLD §13).

**Done:** both seams built; deterministic tests green; the multi-tool-call
question has a plan (verified in Phase 5).

---

## Phase 4 — Thin handlers + API + identity  [AGENT]

Wire the HTTP surface and auth (HLD §4, §9). Handlers are thin I/O over the
registry + repository + Bedrock loop.

- **4a.** REST handlers for the carried-over routes (health, events read,
  work-item/board read + append, `/capture`, `/actions/confirm`) — thin, logic in
  the core.
- **4b.** The **Lambda custom authorizer**: hash the bearer token (HMAC via a
  secret in **Secrets Manager/SSM**) → member + allow policy. WebSocket `$connect`
  authorizes via `?token=`.
- **4c.** The **minting / admin path** (stack-run, not a home-PC CLI): generate a
  strong random token, store only its hash, print plaintext once; `revoke`.
- **4d.** The **`/enroll#token=` receive flow** (HLD §9, Option A): minting emits
  that URL; a QR encodes it; the PWA `/enroll` route reads the token from the URL
  **fragment**, persists to `localStorage`, scrubs the URL. **No in-app QR
  scanner.** (Short-lived typed exchange code = later UX add, not now.)
- **4e. Publish-at-the-boundary** live sync: right after the repository commits,
  the confirm/execute boundary posts the `{entity,id,op}` nudge to the family's
  WebSocket connections (direct-post, HLD §8). A boundary test guards that **all
  writes flow through this one publish point** (completeness without Streams).

**Done:** API + authorizer + minting + enroll flow + direct-post live sync built;
handler/auth tests green; the single-publish-boundary invariant is test-guarded.

---

## Phase 5 — CDK stacks + dev stage integration  [AGENT build / HUMAN deploy]

Everything becomes CDK; the **dev stage** shakes out the cloud-only seams local
testing can't (HLD §11).

- **5a.** CDK stack (**extends the minimal tracer-bullet slice from Part II
  Session 1.5** into the full stack — not a from-zero build): HTTP API, WS API,
  DynamoDB (+ GSIs, TTL), Lambdas, CloudFront, S3 (static assets + **Bedrock-logs
  bucket w/ 180-day lifecycle rule**, HLD §10), IAM (scoped per-Lambda),
  authorizer wiring, Secrets Manager secret. **Per-stage typed props:**
  `bedrockLogFidelity` (default `full`), Bedrock model, throttle limits,
  removal/retention policy. **Billing budget + alert as an AWS Budgets construct**
  (so cost protection deploys with the stack, not a console step — NFR-COST, §2a).
- **5b.** **Bedrock call logging → S3** (HLD §10): full-fidelity default,
  per-call JSON object keyed `bedrock-logs/<family>/<date>/<ulid>.json`;
  `s3:PutObject` grant on the Bedrock-calling Lambda.
- **5c.** Deploy the **full `dev`** stack **[HUMAN: `cdk deploy`]** — `DESTROY`
  removal, disposable table, fake data. (First cloud contact + the IAM / Bedrock
  multi-tool-call / enum / WebSocket-loop questions were de-risked earlier by the
  **tracer-bullet deploy (Part II, Session 1.5)**; this is the *full-stack*
  integration against the real handlers/repository/seams.) **Re-validate at full
  scale:** IAM across all Lambdas, **real Bedrock** with the complete
  `toolConfig` (confirm the Session-1.5 tool-use/enum/multi-tool-call findings
  still hold at full tool count; prompt quality eyeballed), and the full API
  Gateway → authorizer → WebSocket post-back loop.
- **5d.** API Gateway **throttling/rate limits** (token is now the primary
  internet boundary, HLD §9).

**Done:** full dev stack live; IAM + Bedrock + live-sync validated at scale;
findings reconciled with the Session-1.5 tracer bullet; LLD updated if anything
changed at full scale.

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
- **6c.** The `/enroll` page (the 4d receive flow) + the capture / board /
  calendar / proposal-card surfaces over the authenticated API.
- **6d. [HUMAN]** Install the PWA on phones + the wall tablet; device smoke
  (install, enroll via QR, capture→propose→confirm, live update across devices).

**Done:** PWA installs and runs against dev; enroll-by-QR works end-to-end on a
real device; live sync verified across two devices.

---

## Phase 7 — Prod cutover  [AGENT config / HUMAN deploy]

- **7a.** Prod stack props: **`RETAIN` + point-in-time recovery** on the table
  (replaces the old weekly snapshot), tighter throttles, the chosen model,
  `bedrockLogFidelity` as desired.
- **7b. [HUMAN]** Deploy **`prod`**; mint real device tokens; enroll real devices
  via QR.
- **7c. [HUMAN]** Admin/minting hardening follow-on (IP allowlist / second factor
  on the credential-minting path, HLD §9) — tracked, not blocking initial prod.
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

The flow is **local-first** — Sessions 2–7 need no AWS account and run against
fakes / DynamoDB Local / scripted Bedrock, for a fast, free, flake-free loop —
with **one deliberate exception: Session 1.5**, an early throwaway "tracer-bullet"
deploy that de-risks the three cloud-only assumptions (IAM, real Bedrock tool-use,
the WebSocket loop) *before* the local sessions build on them. Shift-left where it
pays (the one unverified, load-bearing assumption), stay local everywhere else.

## Operating rules (every session)

- **TDD, integration-first.** For each unit of functionality, **write the test
  first**, watch it fail, then write code to pass it. **Prefer integration tests
  that exercise a whole interface/flow** (e.g. a capture→propose round trip
  through the real registry + in-memory repo + scripted Bedrock seam; a repository
  method against DynamoDB Local) **over** mock-heavy per-function tests —
  *supplement* with unit tests for specific pure functions (temporal math, schema
  translation, key composition). The goal: tests assert behavior at the seam, not
  implementation detail, so refactors don't break them.
- **DRY + good practice.** One source of truth (the registry drives tools view +
  schema; `DataType` drives param rendering + JSON Schema; the repository is the
  only place table keys live). No copy-paste handlers; factor shared helpers.
  Match the existing code's style and typing discipline (full type hints, no
  `Any`, the engine boundary).
- **The gate is mandatory before a session is "done":** run `make check` and paste
  real output. Never claim green without running it. (Same discipline as the
  current `SKILL.md`.)
- **Tooling is `make` + `scripts/`** (see "Tooling to build" below) — agents use
  targets, not raw commands.
- **Scope + honesty.** Change only what the session names. If blocked, stop and
  report the full error (don't loop). **[HUMAN]** steps: stop and ask; never touch
  the AWS console/credentials.
- **Branch:** all sessions run on the `aws-rebuild` branch (see Git strategy).
  Commit at each green gate with a conventional-commit message.

## Tooling to build (Session 1 establishes it; later sessions extend it)

Mirror the current repo's thin-launcher pattern — a `Makefile` delegating to
`scripts/` and the venv binaries. Target set for the AWS app:

| Target | Does |
|---|---|
| `make setup` | venv + install pinned deps + verify (delegates to `setup.sh`) |
| `make test` | full pytest suite (unit + integration tiers that need no cloud) |
| `make test-core` / `-data` / `-assistant` / `-api` / `-infra` | focused suites per Part-I phase |
| `make lint` / `format` | ruff check(+format-check) / ruff auto-fix |
| `make typecheck` | mypy |
| `make check` | **lint + typecheck + coverage-enforced tests — the gate** |
| `make ddb-up` / `ddb-down` | start/stop **DynamoDB Local** (container) for access-pattern tests |
| `make synth` | `cdk synth` (infra compiles, no deploy) |
| `make deploy-dev` / `deploy-prod` | `cdk deploy` the stage (human-initiated) |
| `make bedrock-smoke` | dev-stage integration checks against real Bedrock (Phase 5) |

Scripts under `scripts/`: `setup.sh` (venv+install+verify), `setup-aws.sh`
(assert non-root admin on `111037110464` + `cdk bootstrap us-east-1`),
`ddb_local.sh` (up/down), `bedrock_smoke.py` (dev-stage checks). Keep each thin
and single-purpose (DRY: `make` calls scripts, scripts don't duplicate `make`).

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
  `BedrockClient` double** (canned LINK JSON + `toolUse` blocks), the DynamoDB
  Local wiring (`make ddb-up/down`, skipped-if-absent), and the boundary-test
  tooling. Put these in `tests/conftest.py` + a `tests/harness/` so Sessions 2–9
  import, not re-build.
- `make synth` on a minimal empty CDK stack (TS CDK) passes.
**Exit:** `make check` green; boundary test green; the shared harness exists and
is documented; `make synth` clean. Commit.

## Session 1.5 — Tracer-bullet dev deploy (de-risk the cloud-only assumptions early)  [HUMAN deploy]
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
marked scaffolding. Commit. *(After this, Sessions 2–7 return to the fast,
free, local-first loop — now building on confirmed assumptions.)*

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

## Session 3 — Data layer: DynamoDB impl on DynamoDB Local  (Phase 2b/2c/2d)
**Goal:** the same tests pass against real DynamoDB semantics.
- `make ddb-up`. Run the **same** protocol-level integration tests from Session 2
  against `DynamoRepository` (parametrize the fixture over both impls — DRY: one
  test body, two backends). Add Dynamo-specific access-pattern tests: sparse-GSI
  archive drop-out, calendar range Query, the two `TransactWriteItems`
  (co-created event; and assert the standalone path is a single `Put`).
- Port the action handlers to the repository (no `boto3` in handlers — the
  boundary test now covers the actions package too).
**Exit:** `make test-data` green against DynamoDB Local; handlers run over the
repo; `make check` green. Commit.

## Session 4 — Assistant: LINK + the scriptable seam  (Phase 3a/3c)
**Goal:** grounding works deterministically with no network.
- **Integration-first:** test the LINK flow end to end — world view in →
  scripted Converse JSON out → validate-against-family → resolved whitelist →
  deep-context (over the in-memory repo). Include malformed-reply → degrade.
- Build the `BedrockClient` protocol + scripted double; implement the LINK call
  shape (not yet real boto3 — that's exercised in Session 7/dev stage).
**Exit:** LINK flow tests green (incl. first-person linking, degrade); `make
check` green. Commit.

## Session 5 — Assistant: PROPOSE tool-use + schema translation  (Phase 3b/3d)
**Goal:** registry→toolConfig, selection-not-execution, enum-over-whitelist.
- **Unit:** `ActionSpec.params`/`DataType` → tool `inputSchema` translation
  (pure); the per-request id-enum overlay.
- **Integration:** focused-context in → scripted `toolUse` block(s) out →
  `ProposedAction` cards; assert **no execution** happens (nothing written), ids
  re-validated against the whitelist, `no_action` handled, and **multiple
  toolUse blocks → multiple cards** (the handler consumes a list; §3.5 fallback is
  a call-count change). Mark the real-model multi-call behavior **to-verify in
  Session 8**.
**Exit:** PROPOSE flow + translation tests green; `make check` green. Commit.

## Session 6 — Thin handlers + authorizer + confirm/execute + live-sync publish  (Phase 4)
**Goal:** the HTTP/auth surface and the execute→publish boundary.
- **Integration-first:** drive each route through its thin handler over the
  in-memory repo + scripted Bedrock: health, events read, work-item/board read +
  append, `/capture` (propose-only, writes nothing), `/actions/confirm` (executes
  via the registry, writes via repo, **publishes once**). Assert the
  **single-publish-boundary invariant** test (§4.3).
- Authorizer: HMAC hash → member/allow (unit for hashing; integration for the
  authorizer→handler context pass). Minting admin path + the `/enroll#token=`
  fragment-read logic (unit-test the parse/scrub).
**Exit:** route + auth + publish-boundary tests green; `make check` green. Commit.

## Session 7 — CDK stack + logging + synth  (Phase 5a/5b, local only)
**Goal:** the whole stack synthesizes with correct scoping; logging adapter done.
- **Infra tests:** `cdk synth` + template assertions — per-Lambda IAM scoping
  (`bedrock:InvokeModel` only on capture, `s3:PutObject` only on logging, table
  grants per handler), the two GSIs, the logs-bucket lifecycle rule, the Budgets
  construct, dev-vs-prod prop differences (RETAIN/PITR, throttles).
- Bedrock-logging adapter → S3 (full|metadata fidelity), unit-tested on object
  shape + fidelity switch.
**Exit:** `make synth` + infra assertions green; `make check` green. Commit.
*(No deploy yet — still local.)*

## Session 8 — Full-stack dev integration  (Phase 5c/5d)  [HUMAN deploy]
**Goal:** integration-test the **real** stack on dev. (First cloud contact already
happened in Session 1.5; this validates the *actual* handlers/repository/seams,
not a tracer bullet.)
- **[HUMAN]** `make deploy-dev` (the full stack now).
- **[AGENT]** `make bedrock-smoke`: the real capture→propose→confirm flow against
  real Bedrock + real DynamoDB + the real authorizer and WebSocket post-back —
  end to end on the deployed dev stack (disposable data). Confirm the Session-1.5
  findings still hold for the real `toolConfig` (the full registry, not the
  2-tool stub) — especially enum adherence across all id-bearing actions and the
  multi-tool-call behavior at full tool count.
- Any divergence from the 1.5 findings (e.g. behavior changes with the larger
  `toolConfig`) is recorded and, if needed, the fallback (§3.5) is already wired
  from 1.5 — adjust the call-count, no reshape.
**Exit:** the full stack validated on dev; findings reconciled with Session 1.5;
LLD updated if anything changed at full scale. Commit.

## Session 9 — Frontend (very simple static PWA on CloudFront)  (Phase 6)  [HUMAN device test]
**Goal:** the installable static PWA against dev, WebSocket live sync, enroll-by-QR
(LLD §9).
- Build the **very simple hand-written vanilla-JS PWA — no framework, no build
  step** (`index.html` + `app.js` + `app.css` + manifest/sw/icon), served static
  from S3+CloudFront. It **renders from the JSON APIs** (`/board`, `/events`,
  `/work-items`, `/capture`, `/actions/confirm`); the old server-rendered
  `/board/view` / `/calendar/view` fragments are **not** built.
- Live sync: open the `WebSocket` (`?token=`), refetch-and-rerender on a nudge,
  reconnect re-sync on open. The `/enroll` fragment-read page. Capture / board /
  calendar / proposal-card surfaces.
- Integration-test the testable units (enroll fragment-read + storage/scrub; the
  WS-nudge→refetch logic) — minimal, matching the simple-client scope.
- **[HUMAN]** install on phone + tablet; device smoke (enroll via QR,
  capture→propose→confirm, cross-device live update).
**Exit:** PWA runs against dev; QR enroll works on a real device; live sync across
two devices. Commit.

## Session 10 — Prod cutover  (Phase 7)  [HUMAN deploy]
**Goal:** prod live, data protected.
- **[AGENT]** finalize prod props (RETAIN+PITR, throttles, model).
- **[HUMAN]** `make deploy-prod`; mint real tokens; enroll real devices; kiosk
  soak. Admin/minting hardening tracked as follow-on.
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
