# AWS Rebuild — Progress / Hand-off Notes

State/resume log for the AWS-native rebuild (see `AWS_START_HERE.md`). Each
session appends: what landed, gate summary, to-verify opened/closed, next session.
A fresh agent context resumes from the bottom.

---

## Session 0.1 — Branch + lift + delete  (done)
- Created branch `aws-rebuild` off `main` (this repo's primary branch is `main`,
  not `mainline`; the branch is additive, `main` untouched).
- Lifted the infra-agnostic core (15 files, `git mv`, byte-identical) into
  `ntake-aws/core/` per the Lift map: engine, action specs, seam contracts
  (`base.py`/`capture.py`), `tools_view.py`, `schemas.py`, `temporal.py`,
  `tokens.py`. Added one new package marker `ntake-aws/core/assistant/__init__.py`.
- `git rm`'d the home-PC runtime per the "Rewrite (do NOT lift)" table: `app/`
  (persistence/SQLAlchemy, FastAPI main/web/web_shell, local_llm, event_emitter,
  config, manage, identity/auth, demo, static, remaining assistant wiring),
  `alembic/`, ops scripts, `setup.sh`/`setup-config.sh`, home-PC `tests/`.
  Kept `scripts/prompt_optimizer.py` + `tools/prompt_optimizer/` + spec/docs.
- Gate: none this session by design (skeleton + `make check` are Session 1).
- Commit: `84ffadc`.
- **To-verify (open, for Sessions 1-2):** lifted files still import old `app.*`
  paths and the deleted `app.persistence.models`; import rewiring and the
  models -> repository/DTO replacement are Session 1-2 work. Reference for any
  removed file: `git show main:<path>`.

## Session 0.2 — Account preflight  (done)
- [AGENT] Authored `./setup-aws.sh` (repo root): asserts non-root admin on
  account `111037110464` / region `us-east-1`, then idempotent
  `cdk bootstrap aws://111037110464/us-east-1`. `--check-only` flag; up-front
  `aws`/`cdk` tooling checks. Validated with `bash -n` + stubbed-`aws` logic
  tests (no real AWS calls by the agent). Commit: `fe2c893`.
- [HUMAN] 0a done + verified: non-root IAM admin user created with
  `AdministratorAccess` + CLI access keys; `aws configure` set to `us-east-1`.
  (A leaked key was rotated during setup.) Confirmed by the owner running
  `./setup-aws.sh --check-only` -> passed (CLI authenticated as the non-root
  admin on `111037110464`).
- [HUMAN] 0b done: the Bedrock "Model access" page is **retired** — serverless
  foundation models now auto-enable on first invocation in commercial regions,
  so there is nothing to manually grant. Caveat: Anthropic/Claude first-time use
  may require submitting use-case details; a real `Converse` success is confirmed
  in Session 1.5 (tracer-bullet), not here. Owner's profile region confirmed
  `us-east-1` (`aws configure get region`).
- [HUMAN] bootstrap done: `./setup-aws.sh` ran clean — identity asserted as
  `arn:aws:iam::111037110464:user/rebuild-admin`, then
  `✅ Environment aws://111037110464/us-east-1 bootstrapped` (CDKToolkit stack,
  default AdministratorAccess execution policy, no trusted accounts).
- Gate: none this session by design (first gate is Session 1).

### To-verify / deferred (open)
- **MFA on the admin user — DEFERRED by owner decision (2026-10-02).** The 0a IAM
  admin user currently has **no MFA**, by explicit choice, to be re-added "once
  the app is actually done." This is a standing risk: a long-lived
  `AdministratorAccess` key with no second factor on a now-public-internet-facing
  account. `setup-aws.sh` does not enforce MFA, so preflight passes without it.
  **Re-add MFA before prod cutover (Session 10 / Phase 7);** fits alongside the
  HLD §9 admin/minting hardening follow-on. Revisit then.

## Session 1 — Skeleton + gate + test harness + tooling  (done)
- **[AGENT]** Stood up the `ntake-aws` package shape (HLD §5): `core/`
  (lifted + rewired), `handlers/`, `adapters/` (empty-but-wired package markers),
  `infra/` (TS CDK), `tests/` (with `core/`, `data/`, `assistant/`, `api/`,
  `infra/`, `harness/`). All Session-1 tooling is **self-contained under
  `ntake-aws/`** (decision: the stale root `Makefile`/`pyproject.toml`/
  `requirements.txt` are the old `mainline` app's — left untouched).
- **Import rewiring (Session-1 scope):** rewired the clean lifted core off the old
  `app.*` paths onto `core.*`: `engine/engine.py` (boundary target — imports
  nothing infra-specific), `engine/__init__.py`, `temporal.py`,
  `assistant/capture.py`, `assistant/tools_view.py`, `actions/meta.py`. `meta.py`
  is kept **live** by typing its one spec against the engine's base
  `ActionContext` (dropping the parked `NtakeActionContext` dep); Session 2
  re-specializes it when the registry is ported.
- **Parked for Session 2 (flagged, excluded from the gate):** the
  persistence-coupled modules still importing `sqlalchemy` + the deleted
  `app.persistence.models` — `core/actions/{context,shared,registry,work_items,
  events}.py` and `core/assistant/base.py`. Each carries a ⚠️ PARKED banner;
  `pyproject.toml` excludes all six from mypy + coverage (kept in sync with the
  banners). Session 2 ports them onto the `Repository` seam + lifted DTOs.
- **Tooling:** `Makefile` (thin launcher) + `scripts/` per the Tooling table —
  `setup.sh` (venv + pinned deps + infra npm deps + verify), `ddb_local.sh`
  (up/down, **skipped-if-absent** — no docker in this env), `bedrock_smoke.py`
  (Session-8 placeholder, exits non-zero), and `setup-aws.sh` **relocated** from
  the repo root to `ntake-aws/scripts/` (now `make setup-aws` /
  `bash scripts/setup-aws.sh`). Targets: `setup`, `test`, `test-core/-data/
  -assistant/-api/-infra`, `lint`, `format`, `typecheck`, `check` (gate), `ddb-up/
  -down`, `synth`, `deploy-dev/-prod`, `bedrock-smoke`, `setup-aws`, `clean`.
- **Pinned deps** (`requirements.txt`): pydantic 2.13.5, boto3/botocore 1.43.55
  (used from Session 2), pytest 9.1.1 + pytest-cov 7.1.0, coverage 7.16.0,
  ruff 0.16.5, mypy 2.3.1, boto3-stubs[dynamodb,bedrock-runtime]. No fastapi /
  sqlalchemy / uvicorn / alembic (dropped). Infra pins (`infra/package.json`):
  `aws-cdk-lib` 2.173.4 + `constructs` 10.4.2; the CDK **CLI** is the system
  `cdk` (2.1144.0), *not* a project dep (documented in the README).
- **Boundary test (TDD, real functionality):** `tests/test_boundary.py` asserts a
  fresh import of `core.engine.engine` leaks none of
  `{boto3, botocore, sqlalchemy, fastapi, app}` and reaches none of the six parked
  modules. Tooling in `tests/harness/boundary.py` (reused for later boundaries,
  e.g. the single `publish_change` call site). Verified non-vacuous (the helper
  fires on a deliberately-leaked `concurrent`).
- **Shared test harness (the DRY backbone, LLD §8):** `tests/conftest.py` + a
  `tests/harness/` package — a **parametrize-over-both-repos** `repo` fixture
  (`memory` runs now via a `PlaceholderRepository`; `dynamo` is skipped-if-absent
  AND not-implemented-until-Session-3), a **scripted `BedrockClient` double**
  (`ScriptedBedrockClient` + `link_response`/`propose_response` helpers — Converse
  shaped, substring-keyed, deep-copy-isolated, records calls), the **DynamoDB
  Local probe** (`requires_dynamodb_local` marker), and the boundary tooling.
  Self-tested in `tests/test_harness.py`. Sessions 2-9 import these, not rebuild.
- **Core unit tests (TDD the lifted logic):** `tests/core/` re-expresses the
  behavioral contracts for the live core — engine registry/`ActionSpec`/`DataType`/
  `propose_bounded`, temporal UTC↔local (incl. DST spring-forward/fall-back
  edges), token HMAC, schemas DTO contracts, tools view, `no_action`.
- **Infra:** `infra/` is a minimal **empty** `NtakeStack` (typed `NtakeStageProps`
  scaffold per LLD §7.2) instantiated for `dev` + `prod`; `tsc` compiles
  `bin/`+`lib/`, `cdk.json` runs `node bin/ntake-aws.js`.
- **Gate:** `make check` **GREEN** — ruff lint + format-check clean, mypy clean
  (38 source files), **69 passed / 5 skipped**, **100% core coverage** (≥95 gate).
  `make synth` **clean** — TS compiles, both `NtakeStack-dev` / `NtakeStack-prod`
  templates synthesized to `infra/cdk.out/`.
- No AWS interaction (local-only, as scoped).

### To-verify / deferred (open)
- **Session 2 brings the six parked modules back under the gate** (repository +
  DTO port, AWS_LLD §2); keep the `pyproject.toml` exclude list and the ⚠️ PARKED
  banners in sync as they return. The lifted `core/schemas.py` is still **int-id**
  — the ULID-string ripple (AWS_LLD §1) is applied in Session 2 alongside the
  repository/DTOs.
- `core/actions/shared.py` (parked) still imports `app.persistence.temporal`; its
  rewire to `core.temporal` happens in the Session 2 port (it is not on the gate).
- `temporal._zone` wraps only `TypeError`/`ValueError` → `ActionError`; an unknown
  *string* zone raises `ZoneInfoNotFoundError` (a `KeyError`) unwrapped. Left
  as-is (lifted behavior); noted by a test. Revisit if it ever matters.

### Next session
**Session 1.5 — Tracer-bullet dev deploy** (de-risk the three cloud-only
assumptions: IAM, real Bedrock tool-use, the API-GW → authorizer → WebSocket
post-back loop). This is the **one deliberate [HUMAN]-deploy exception** before
the local-first Sessions 2-7. It builds a minimal throwaway CDK slice (trivial
table, one Lambda behind the HTTP API, the authorizer, a WS `$connect`/
`$disconnect` + one hard-coded post-back, the Secrets Manager secret), the
operator runs `make deploy-dev`, and the agent validates the three seams against
the deployed slice — feeding the multi-tool-call + enum findings back into
AWS_LLD §3.5. (See AWS_PLAN Part II, Session 1.5.)

## Session 1.5 — Tracer-bullet dev deploy  (done — with one deferred seam)
- **[AGENT]** Built a clearly-marked **throwaway** tracer slice. Decision: a
  **separate `TracerStack`** (deployed as `TracerStack-dev`, dev-only) rather than
  extending the empty `NtakeStack` — so Session 5 deletes it in one move without
  disturbing the real stack. Confirmed with the user.
  - `ntake-aws/tracer/`: `authorizer.py` (device-token → member, **HTTP API
    simple-response** `{isAuthorized,context}`, reuses the real
    `core.tokens.hash_token`), `app_handler.py` (IAM proof via scoped DynamoDB
    put+get), `bedrock_tracer.py` (2-tool `toolConfig` + `no_action`,
    `toolChoice:any`, enum-over-whitelist; parse/summarize for §3.5),
    `ws_handler.py` (`$connect` writes a connection item; `$disconnect` cleans up).
  - `infra/lib/tracer-stack.ts`: 1 DynamoDB table, 1 Secrets Manager secret, 5
    Lambdas each with its **own scoped role** (authorizer read-only on the table;
    app/ws read-write on the table; ws-connect `execute-api:ManageConnections`;
    bedrock `bedrock:InvokeModel` scoped to the model — never `*`), HTTP API
    (authorized) + WebSocket API.
  - Local tests under the existing harness: `tests/api/test_tracer_authorizer.py`,
    `tests/api/test_tracer_http_ws.py`, `tests/assistant/test_tracer_bedrock.py`.
- **[HUMAN]** `make deploy-dev` (→ `cdk deploy TracerStack-dev`) — the first
  deploy. Succeeded on `111037110464` / us-east-1.
- **Gate GREEN** at close: ruff clean, mypy 46 files, **91 passed / 5 skipped,
  100% core coverage**. **`make synth` clean** (NtakeStack-dev/-prod untouched,
  TracerStack-dev added). Commit on `aws-rebuild` (not pushed; additive branch).

### Three-seam results
- **IAM — PROVEN ✓.** `GET /tracer-iam` with a seeded token → 200 JSON: scoped
  DynamoDB put+get succeeded, `authorizer_context {member_id:MEM#alex,
  family_id:FAM#tracer}` passed through; no-token → 401. The scoped per-Lambda
  role works end-to-end (no AccessDenied) and the authorizer→handler context pass
  is confirmed.
- **WebSocket — connect/routing/handshake PROVEN ✓; delivery DEFERRED.** The raw
  stdlib client got `101 Switching Protocols` (API GW accepts `$connect`, routes
  to the Lambda, which wrote the connection item). **Finding:** posting back to
  the *connecting* socket from inside `$connect` does **not** work (hangs ~7s then
  fails — an API GW quirk). The real design never does this — nudges are posted
  from the **confirm/execute boundary** (a separate invocation to already-
  established connections, AWS_LLD §4.2), so delivery-to-a-listening-client is
  validated at the correct seam in **Session 6/8**, not here. The tracer's
  self-post was removed (YAGNI; don't build the artificial path).
- **Bedrock — BLOCKED on account authorization; §3.5 question OPEN/DEFERRED.**
  Every `Converse` call (even plain text, no tools) returns `ValidationException:
  "Operation not allowed"` for both Claude (Haiku 4.5 via `us.` profile) and Nova
  Lite; the Bedrock Playground (as root) also does not respond. Account health is
  fine (no suspension; valid payment; the billing-page restrictions were just the
  IAM-user-can't-see-billing wall). This is a **first-time, account-level Bedrock
  authorization** that only AWS grants — **a support case has been filed** (as
  root). IAM/request-shape are correct (the call *reaches* Bedrock). The
  multi-tool-call + enum questions are therefore **unanswered** — written into
  AWS_LLD §3.5 as deferred, with the safe decision locked so Sessions 4–5 are not
  blocked: handler consumes a **list** of toolUse blocks (1-or-many, reshape-free),
  `toolChoice:any` is design-intent-to-confirm, **one-primary-proposal-per-capture
  is the default** until observed otherwise.

### Findings / decisions recorded in AWS_LLD §3.5
- Claude 3 Haiku (`anthropic.claude-3-haiku-20240307-v1:0`) is **retired**; modern
  Claude is **inference-profile-only** → pin `us.anthropic.claude-haiku-4-5-...`
  and widen the Bedrock IAM to the inference-profile ARN **+** underlying
  foundation-model ARNs across us-east-1/us-east-2/us-west-2 (still model-scoped).
- HTTP API authorizer: use **simple response** (payload format 2.0), not an IAM
  policy — the IAM-policy/format-1.0 shape was a silent-fail footgun (routes
  returned 200 regardless of token until switched).
- Route naming: avoid `/ping` — it is intercepted by an edge/network health-probe
  responder before reaching API Gateway (returned a canned "Healthy Connection").
  Tracer routes are `/tracer-iam`, `/tracer-bedrock`.
- Added a **YAGNI** operating rule to AWS_PLAN (learned twice this session: a
  dual-shape authorizer and a speculative `inferenceConfig`, both removed).

### To-verify / deferred (open)
- **Bedrock invocation blocked on the AWS support case.** When granted (no
  redeploy needed), run `scripts/bedrock_bisect.py
  us.anthropic.claude-haiku-4-5-20251001-v1:0` — it bisects plain-text → tools →
  `auto` → `any` → the exact tracer config. Record the real multi-tool-call + enum
  answer in AWS_LLD §3.5 and reconcile at full tool count in Session 8.
- **WebSocket delivery** (server → listening client) is proven at the execute
  boundary in Session 6/8, not in the tracer.
- The throwaway `tracer/` package, `TracerStack`, and `scripts/tracer_validate.py`
  / `nova_probe.py` / `bedrock_bisect.py` / `ws_check.py` are **deleted** when
  Session 5 builds the real resources into `NtakeStack` and `make deploy-dev` is
  pointed back at `NtakeStack-dev`.

### Next session
**Session 2 — Data layer: repository contract + in-memory impl** (local-first; no
AWS, no Bedrock). Build the `Repository` protocol + `InMemoryRepository`,
integration-first, against the Session-1 harness. (See AWS_PLAN Part II,
Session 2.) The Bedrock support-case outcome is independent and backfills §3.5
whenever it lands.

## Session 2 — Data layer: repository contract + in-memory impl  (done)
- **[AGENT]** Built the data-layer seam, local-first (no AWS, no Bedrock, no
  DynamoDB Local — that is Session 3). TDD + integration-first: flow tests
  written against the protocol first (watched RED), then the impl to GREEN.
- **Repository Protocol** (`core/repository.py`): the method set from AWS_LLD
  §2.1 **verbatim** — reads (`get_work_item`, `get_member`, `list_members`,
  `get_event`, `list_board`, `list_calendar`, `list_done_work_items`,
  `get_family`), intra-item + cross-item writes (`put_work_item`,
  `update_work_item`, `append_update`, `put_event`, `update_event`,
  `create_event_from_update`, `delete_event`, `archive_work_item`), connections
  (`put_connection`, `list_connections`, `delete_connection`). **No `commit()`**.
  Derived from the parked handlers (YAGNI — no speculative methods). Also homes
  the **pure key/sort helpers** as the single source of table-key knowledge
  (reused byte-for-byte by Session 3's Dynamo impl): `board_sort_key`
  (STATUS#…#POS# zero-padded width 6), `calendar_sort_ts` (UTC start for timed;
  family-midnight-UTC for all-day), `work_item_due_sort_ts`, and the
  `FAM#`/`WI#`/`EV#`/`MEM#`/`CONN#` composers.
- **ULID ripple** (`core/schemas.py`, AWS_LLD §1): every id → `str` across the
  API DTOs; added the **repository DTOs** — `WorkItem` (co-located aggregate:
  nested `updates` log + `checklist` + reserved `log_segments` spill slot),
  `Event` (flat + denormalized `provenance` + `source_update_id`), `Member`,
  `Family`, `CalendarRow`, plus `WorkItemStatus`/`CalendarKind` `StrEnum`s and
  `BOARD_COLUMNS = (todo, on_deck, doing, done)`.
- **`InMemoryRepository`** (`core/repository_memory.py`): dict-backed, deep-copy
  value semantics (mirrors DynamoDB by-value items), family-scoped (the partition
  boundary), board grouping/ordering + sparse-archive + unified calendar via the
  shared helpers. Replaced the Session-1 `PlaceholderRepository` behind the
  **same `"memory"` factory key**, so the parametrized `repo` fixture kept working
  with no test rewrites. `seed_family` is an **impl-only** provisioning affordance
  (members/families are out-of-band of the protocol, §2.1) — the harness
  `seed_family(repo, …)` dispatches per-backend (Dynamo branch wired in S3).
- **Tests (harness reused, not rebuilt):** `tests/data/test_repository_flows.py`
  — 20 **impl-agnostic** flow tests via the `repo` fixture (create→append→read
  aggregate; board grouping/ordering; put-event→list-calendar range + ordering;
  archive drops off board + calendar; due-date bridge; co-created-event; family
  scoping; connections) — ready to run **unchanged** on `DynamoRepository` in
  Session 3. Plus `test_repository_helpers.py` (pure helpers) and
  `test_repository_memory.py` (impl edge/error paths). Rewrote
  `tests/core/test_schemas.py` to ULID strings + new-DTO coverage.
- **Parked modules stay parked** (handlers port in Session 3, per AWS_PLAN exit).
  Exclude list **unchanged** (same 6 modules); refreshed the ⚠️ PARKED banners +
  `pyproject.toml` header/comments so they name **Session 3** as the port session
  (the seam they port onto was built here in Session 2).
- **Gate GREEN:** `make check` — ruff lint + format clean, mypy clean (51 source
  files), **134 passed / 24 skipped, 100% core coverage** (≥95 gate).
  `make test-data` green (37 passed / 20 skipped). Boundary test still green
  (`core.engine.engine` leaks nothing; `repository.py` imports only
  `zoneinfo` + `core.temporal`, no `boto3`). `make synth` clean (stacks
  untouched). Commit `8a1836a` on `aws-rebuild` (not pushed; additive branch).
- No AWS interaction (local-only, as scoped).

### To-verify / deferred (open)
- **Session 3 ports the six parked handlers onto this `Repository` seam**
  (AWS_LLD §2) and brings them back under the gate — keep the `pyproject.toml`
  exclude list + ⚠️ PARKED banners in sync as each returns. Fidelity notes for
  the port: the handlers raise `ActionError` on a missing target, whereas the
  repo raises `KeyError` — the ported handler translates. `shared.py`'s
  `_append_assistant_update` returns the created update so `create_event` can set
  `source_update_id`; the repo models this as `create_event_from_update(ev,
  wi_log_entry)` taking a pre-built `WorkItemUpdate` + an `Event` carrying
  `provenance.work_item_id`. `archive_all_done` / checklist add+check-off are
  handler-level loops over the repo reads/writes (no new repo methods needed).
- **`core/actions/shared.py` rewire** to `core.temporal` (it still imports
  `app.persistence.temporal`) happens in the Session 3 port.
- The Bedrock support-case outcome remains independent (backfills AWS_LLD §3.5
  whenever it lands via `scripts/bedrock_bisect.py`); it does not block Session 3.

### Next session
**Session 3 — Data layer: DynamoDB impl on DynamoDB Local** (Phase 2b/2c/2d).
Wire the `"dynamo"` factory to `DynamoRepository` (boto3 over the single table,
reusing the §1 key helpers from `core/repository.py`), run the **same** flow
tests against it (`make ddb-up`; parametrize fixture over both backends), add
Dynamo-specific access-pattern tests (sparse-GSI archive drop-out, calendar range
Query, the two `TransactWriteItems`), and **port the parked action handlers** onto
the `Repository` seam (no `boto3` in handlers — the boundary test extends to the
actions package). (See AWS_PLAN Part II, Session 3.)

---

## Decision — Two-tier testing model (2026-10-02, owner)
**Supersedes the "local-first for everything, cloud integration only at Sessions
5/8" operating model** stated in the earlier plan/notes. Owner's call: build a
**dev-stage integration incrementally** instead.

- **Tier 1 — local/fast (default gate, `make check`):** ruff + mypy + the
  unit/contract suite against `InMemoryRepository` + scripted Bedrock. **No
  Docker, no DynamoDB Local, no AWS, no credentials, no heavy deps.** Always green
  offline — the TDD inner loop and what a fresh agent context runs.
- **Tier 2 — remote/integration (`make integration`), incremental:** runs the
  **same** flow/access-pattern tests against the **real dev stage**, and can
  deploy. **One target, deploy is an arg:** `make integration` tests whatever is
  deployed; `make integration DEPLOY=1` runs `cdk deploy NtakeStack-dev` first.
  The target **self-checks `aws sts get-caller-identity`** and stops with
  configure instructions if creds are missing/wrong-account (never silently
  skips). **[HUMAN]-invoked** — the agent writes it + surfaces command/results;
  the human runs anything that deploys to / writes the account. The **human
  integration test is retained** (owner explicitly wants it).
- **Tier 2 is always WIRED, and self-skips on unmet preconditions (clarified
  2026-10-02).** Tier 1 is the TDD red-green loop; Tier 2 is the per-session
  dev-integration *gate* the human invokes to close a session. A session must
  **build its real Tier-2 path even when it cannot run yet** — the path
  self-checks preconditions and stops cleanly as a recorded **[HUMAN]** follow-up,
  **never silently skipping and never faking a pass**: credentials (via `sts`),
  and — for model-dependent slices (LINK/PROPOSE/capture, Sessions 4–8) — a
  **Bedrock-authorization self-check** (the account is invocation-blocked, §3.5).
  So "the real model can't run yet" is handled by a wired, self-skipping Tier-2
  path, **not** by declaring a session Tier-1-only or dropping its Tier-2 gate.
  When the Bedrock ticket clears, `make integration` exercises the real call with
  **no code change**. (This is now a standing Operating rule in `AWS_PLAN.md`.)
- **Each feature session from Session 3 on = code + its infra slice (into
  `NtakeStack`) + its dev integration.** The dev stage grows gradually, not in a
  Session-5/8 big bang. Sessions 5/8 shrink: §5a/§5b work distributes into the
  feature sessions; Session 8 becomes a full-stack reconciliation sweep + the
  full-tool-count §3.5 Bedrock reconciliation (not first cloud contact).
- **DynamoDB Local is DROPPED (YAGNI):** no `ddb_local.sh`, no `make ddb-up/down`,
  no `requires_dynamodb_local` marker, no backend-parametrized `repo` fixture.
  Tier 1 is in-memory; Tier 2 is the real table. The standalone `bedrock_smoke.py`
  / `make bedrock-smoke` also fold into `make integration`.

**Specs updated now (this change):** `AWS_PLAN.md` (Part II intro, Operating
rules, Tooling table, Sessions 3–8 exit criteria, Part I Phase 2), `AWS_HLD.md`
(decision 9, §5 package-shape, §11 testing, §14), `AWS_LLD.md` (§2.2, §8 test
strategy). **Tooling NOT changed yet:** the `Makefile`/`scripts/` still carry the
old `ddb-up`/`ddb-down`/`bedrock-smoke` targets + `ddb_local.sh` — the actual
`make integration` build + the removal of the DynamoDB-Local harness happen **in
Session 3** (that is where the target has a real consumer; building it now would
leave a half-wired target against YAGNI). Sessions 0–2 historical notes above are
left intact (they ran under the old model; the records stay truthful).

### Carry-forward env note (container runtime)
This machine has **Finch** (`~/.toolbox/bin/finch`, 1.19.0) but **not Docker**;
Finch's VM can't init here (sudo blocked). Irrelevant under the new model — Tier 1
needs no runtime at all, and Tier 2 hits the **real** dev table (not a local
container). The old "need Docker/DynamoDB Local for Session 3" blocker is **gone**.

### Next session (restated under the two-tier model)
**Session 3 — Data layer: DynamoDB impl + first dev-stage integration slice.**
(1) Add the **real single table** `ntake-<stage>` (PK/SK + GSI1 board + GSI2
calendar + TTL, per-stage props) into `NtakeStack` — the Session-5a table slice
pulled forward. (2) Build `DynamoRepository` (boto3, endpoint-/region-configurable,
reusing the `core/repository.py` key/sort helpers byte-for-byte). (3) Port the six
parked handlers onto the `Repository` seam (no `boto3` in handlers; extend the
boundary test to the actions package; shrink the `pyproject.toml` exclude/omit
lists + remove the PARKED banners as each returns). (4) **Build `make
integration`** (sts self-check + optional `DEPLOY=1` + the Tier-2 suite) and
**delete the DynamoDB-Local harness** (`ddb_local.sh`, `ddb-up`/`ddb-down`,
`requires_dynamodb_local`, the `dynamo` fixture param; fold `bedrock-smoke` in).
**Exit:** `make check` (Tier 1) green with handlers over the repo + parked modules
back under the gate; `make integration` (Tier 2, [HUMAN]-invoked) green against the
real `ntake-dev` table — or, if creds unavailable this sitting, land the code +
`make integration` wiring with Tier 1 green and record the dev run as a [HUMAN]
follow-up (don't fake it); `make synth` clean. (See AWS_PLAN Part II, Session 3.)

---

## Session 3 — Data layer: DynamoDB impl + first dev-stage integration slice  (done — Tier-1 green; Tier-2 wired, dev run a [HUMAN] follow-up)
First session under the two-tier model: shipped code **+** its infra slice **+**
its (wired, not-yet-run) dev integration. **No AWS credentials this sitting**, so
Tier 2 is built + wired with Tier 1 green and the real-table run recorded as a
[HUMAN] follow-up (the judgment call baked into the session scope — not faked).

- **[AGENT] Infra slice (into `NtakeStack`, not the tracer).** Added the **real
  single table** `ntake-<stage>` (`infra/lib/ntake-stack.ts`): PK/SK, **GSI1**
  (board) `GSI1PK=FAM#<fam>#BOARD` / `GSI1SK=STATUS#…#POS#…`, **GSI2** (calendar)
  `GSI2PK=FAM#<fam>#CAL` / `GSI2SK=TS#…`, on-demand billing, **TTL attr `ttl`
  reserved** (nothing writes it in v1), per-stage props consumed for the first
  time (dev `DESTROY`/no-PITR, prod `RETAIN`/**PITR**). `TableName` CfnOutput for
  the integration harness. The Session-5a table slice, pulled forward. `make
  synth` **clean** — `NtakeStack-dev`/`-prod` both synthesize (verified table +
  2 GSIs + TTL + dev `Delete`/prod `Retain`+PITR in the templates); `TracerStack-dev`
  untouched.
- **[AGENT] `DynamoRepository`** (`adapters/dynamo_repository.py`): boto3 resource
  over the single table, full `Repository` protocol, **reusing
  `core/repository.py` key/sort helpers byte-for-byte** (the single source of
  table-key knowledge — the adapter never re-derives keys). DTO⇄item via
  `model_dump(mode="json")` + `model_validate` (ISO strings), key/`_type` attrs
  stripped on read. **Sparse-GSI write rules:** GSI1 only when `archived_at` null;
  GSI2 on events + due-dated unarchived work items (clearing due / archiving drops
  it). **Two `TransactWriteItems`:** `create_event_from_update` (event `Put` +
  work-item `list_append` `UpdateItem`); standalone `put_event` stays a **single
  `Put`**. `append_update` is an atomic `list_append` `UpdateItem`. Client is
  **endpoint-/region-configurable** (so the exact code Tier 1 runs in-memory is
  what Tier 2 runs against the real table). Added `core/ids.py` — a **stdlib ULID
  minter** (no new dependency, YAGNI) for server-side id minting; added
  `TargetType` StrEnum to `core/schemas.py` (names domain entities; lives with the
  DTOs).
- **[AGENT] Ported the six parked handlers** onto the `Repository` seam + lifted
  DTOs (`core/actions/{context,shared,registry,work_items,events,meta}.py`,
  `core/assistant/base.py`): dropped the SQLAlchemy `Session`/`app.persistence.models`
  deps; `shared.py` rewired off `app.persistence.temporal` onto `core.temporal`;
  `meta.py` re-specialized to the ported `NtakeActionContext`. Fidelity rules
  honored: **`KeyError`→`ActionError`** translation in the loaders; the co-created
  event uses `create_event_from_update(ev, log_entry)` with the log-entry id
  minted up front for `source_update_id` + denormalized `provenance`;
  `archive_all_done` + checklist add/check-off are **handler-level loops** over
  repo reads/writes (**no new repo methods** — YAGNI). Detached-DTO writes go
  through `update_work_item`/`update_event` `changes` dicts (not autoflush).
  `member_id` param → ULID `STRING`. All six **⚠️ PARKED banners removed** and the
  `pyproject.toml` mypy-exclude + coverage-omit lists **deleted** (both empty now).
- **[AGENT] Tier-1 harness updates.** Boundary test **extended to the actions
  package** (`core.actions.registry` imports none of `boto3`/`sqlalchemy`/`fastapi`/
  `app`; the `DynamoRepository` adapter is the only `boto3` home). New TDD handler
  flow tests (`tests/data/test_action_handlers.py` + `test_action_validation.py`)
  + a describe/render sweep over the whole registry (`tests/core/test_action_specs.py`)
  + the stage-1 seam test (`tests/assistant/test_base_seam.py`). **DynamoDB-Local
  vestige deleted:** `scripts/ddb_local.sh`, `tests/harness/ddb_local.py`, the
  `requires_dynamodb_local` marker, the `make ddb-up/ddb-down` targets, and the
  skipped `dynamo` fixture param — the `repo` fixture is now **in-memory only**
  (one factory). The standalone `scripts/bedrock_smoke.py` + `make bedrock-smoke`
  folded away (real Bedrock checks join `make integration` once the capture slice
  lands, Session 4+).
- **[AGENT] `make integration` (Tier 2) built.** `scripts/integration.sh`:
  (a) `aws sts get-caller-identity` self-check — **stops with configure
  instructions** if creds missing or wrong-account (**never silently skips** —
  verified: it stopped cleanly here with no creds); (b) optional `DEPLOY=1` →
  `cdk deploy NtakeStack-dev`; (c) `describe-table` guard; (d) runs the Tier-2
  suite against the real `ntake-dev`. The Tier-2 tree (`tests/integration/`) has
  its own conftest whose `repo` fixture **overrides** the in-memory one with a
  `DynamoRepository` on the real table, so `test_dynamo_flows.py` re-runs the
  **same 20 flow bodies** unchanged (one body, two tiers) alongside 4
  **Dynamo access-pattern tests** (`test_dynamo_access_patterns.py`): sparse-GSI1
  archive drop-out, GSI2 calendar range Query, co-created `TransactWriteItems`
  both-sides, and **standalone create = single `Put`** (mock call-count spy). Tier
  1 ignores `tests/integration` (`--ignore`), so the gate never needs AWS. Suite
  **collects 24 tests without AWS** (import/wiring proven).
- **Gate GREEN (Tier 1).** `make check`: ruff lint+format clean, **mypy clean (66
  source files)**, **205 passed / 13 skipped**, **99.41% core coverage** (≥95
  gate). `make synth` clean. No AWS interaction by the agent.

### Tier-2 dev run — CLOSED GREEN (2026-10-02): 19/19 against real `ntake-dev`
The owner ran `make integration` against the deployed `ntake-dev` table. It took
three iterations and surfaced **four real bugs Tier 1 could not** — exactly the
cloud-only truths the tier exists to catch — all now fixed, final run **19 passed**:
  1. **Co-created-event `TransactWriteItems` ValidationException (list_append
     operand type M).** The transaction's `list_append(if_not_exists(updates,
     :empty), :u)` was operand-type-fragile (resource-level `append_update` with
     the same expression passed, so it was specific to the hand-serialized
     transaction). **Fix:** read the work item, append in Python, `SET updates =
     :all` in the transaction — still one atomic `TransactWriteItems`.
  2/3. **Board/calendar GSI reads lagged a just-written mutation** (archived item
     still on the board; due-item not yet on the calendar). Root cause: **GSIs are
     eventually consistent** (no `ConsistentRead` on a GSI); the adapter writes
     correct keys synchronously. **Fix (test-tier):** the GSI-backed behaviors run
     as **native `poll_until`-based** access-pattern tests that converge on the
     *exact* expected result (correct for appear + drop-out); `test_dynamo_flows.py`
     re-runs only the **strongly-consistent base-table** shared bodies.
  4. **Transaction `Put` "Type mismatch for key PK expected: S actual: M".** The
     root `make integration` finding (seen only once `CancellationReasons` were
     surfaced): serializing with `TypeSerializer` and handing the result to
     `self._table.meta.client` double-wrapped it — the **resource-attached** client
     re-applies boto3's serialization hooks (`{"S":v}` → `{"M":{"S":v}}`). **Fix:**
     use a **plain low-level `boto3.client("dynamodb")`** (`self._ddb`) for the
     transaction — no resource hooks, one explicit serialize pass. This also ends
     the resource/low-level mixing cleanly (resource `Table` for single-item ops,
     plain client for the one transaction).
  Plus a **test-isolation fix**: the test factory minted deterministic per-process
  ids, which collided with leftover rows on the **persistent** dev table across
  runs (caught by the exact-match raw-GSI assertion). Now the factory mints real
  ULIDs (`core.ids.new_ulid`), unique across runs — DRY: tests mint ids like prod.
  **Added (owner-requested, gap #1):** two **raw-GSI direct-query** tests that
  assert the index itself holds/drops the `STATUS#…#POS#…` / `TS#…#EV#|WI#` keys —
  verifying GSI1/GSI2 independently of `list_board`/`list_calendar` (previously the
  index was only verified transitively through the repo's own reads).
- **Deferred test gaps (owner-scoped, 2026-10-02 — not built, YAGNI):**
  (a) **transaction rollback** — the happy path asserts both sides land; a forced-
  failure test proving *neither* lands (the property that justifies the
  transaction over two calls) is not written. Worth adding when the confirm/execute
  path is wired (Session 6). (b) **concurrency / last-write-wins** (`updated_at`)
  — explicitly a v1 non-goal (AWS_LLD §1.4). (c) **dev-table cleanup — RESOLVED
  (owner-requested).** Test-minted ids now carry an identifiable ``itest-`` prefix
  (opt-in `factories.set_id_prefix`, set only by the integration conftest; Tier-1
  ids stay plain), so every test row is ``FAM#itest-<ulid>`` — recognizable in the
  table. A session-scoped autouse fixture sweeps all ``FAM#itest-`` partitions
  **before** (self-heals rows leaked by a crashed prior run) **and after** the run
  (best-effort; dev is DESTROY-able). Verified: post-run
  `scan begins_with(PK,"FAM#itest-")` → **Count 0**. (Note: ~132 orphaned rows
  from pre-cleanup runs, plain-ULID ids, remain untouched by the prefix sweep —
  harmless; clear with `cdk destroy NtakeStack-dev` + redeploy if a clean slate is
  wanted — now a one-liner: **`make dev-reset`** (destroys NtakeStack-dev; dev
  only; recreate with `make integration DEPLOY=1`).)
- **Residual coverage:** one trivial fallback line + a few partial branches in
  `events.py` (all-day `end_date` defaulting; the no-title create describe) remain
  — 99.41% is well over the 95 gate; left as-is (YAGNI).
- **Bedrock support case** (independent of Session 3) still backfills AWS_LLD §3.5
  via `scripts/bedrock_bisect.py` whenever AWS grants invocation. The throwaway
  `tracer/` + `TracerStack` + tracer scripts are still deleted in Session 5.
- `make deploy-dev` still points at `TracerStack-dev` (Session 1.5's deployed
  slice); `make integration DEPLOY=1` deploys `NtakeStack-dev` directly via the
  script. Reconciled in Session 5 when the tracer is removed and `deploy-dev`
  repoints at `NtakeStack-dev`.

### Next session
**Session 4 — Assistant: LINK + the scriptable seam** (Phase 3a/3c). Build the
`BedrockClient` protocol + scripted double and the LINK constrained-JSON Converse
seam (world view → `{work_item_ids, event_ids, member_ids}` → validate-against-
family → whitelist; first-person linking; malformed→degrade), driven integration-
first over the in-memory repo at Tier 1. The real-model LINK run is the Tier-2/
[HUMAN] increment, gated on the Bedrock account-auth support case (§3.5). (See
AWS_PLAN Part II, Session 4.)


## Pivot — Bedrock → Anthropic API  (done, before Session 4)
The assistant seams moved off **Amazon Bedrock** onto the **Anthropic Messages
API** (`api.anthropic.com`), because the Session 1.5 tracer found Bedrock
invocation blocked by an account-level hold only AWS can lift (LLD §3.5). A
provider swap, not an architecture change: LINK ⇒ PROPOSE, registry→tools, the
scriptable seam all unchanged — only the wire protocol (Converse → Messages) and
the credential path (`bedrock:InvokeModel` IAM → an API key in Secrets Manager).
- **Docs:** HLD (decisions §2/§5/§6 + new §10 pivot rationale, §2a posture, §3
  topology, §4 flows, §5 package shape, §7/§7a seams + LLM-tier, §9 Secrets
  Manager, §10 logging, §11 props, §12–§14) and LLD (§3.1–§3.6, §6, §7, §8) fully
  pivoted. `REQUIREMENTS` §5a unchanged in substance (Bedrock→Anthropic wording).
  **Jev / GENERATE⇒DECIDE recorded as a deferred post-v1 refactor (LLD §3.6)**,
  with PROPOSE's action/parameter split point documented as the designated seam.
- **CDK:** props renamed (`bedrockModelId`→`anthropicModelId`,
  `bedrockLogFidelity`→`assistantLogFidelity`); an **empty** `anthropic-api-key`
  Secrets Manager secret added to `NtakeStack` (value set out-of-band). Tracer
  left intact (deleted Session 5). `make secrets-anthropic` + `scripts/
  secrets-anthropic.sh` store `{api_key, workspace_id}` JSON (key prompted, never
  in argv; workspace id is account-level so the Messages API needs the
  `anthropic-workspace-id` header).
- **Reality-check:** `scripts/spike/link_probe.py` (throwaway) hit the real
  Messages API and resolved the open §3.1 question — **forced-tool** (a single
  `record_links` tool whose `input_schema` IS the `{ids}` object) over
  prompt-and-parse (which fenced the JSON + appended prose). Kept as reference
  until Session 4 green; safe to delete now.

## Session 4 — Assistant: LINK + the scriptable seam  (done — Tier-1 + Tier-2 green)
Built the whole LINK stage, TDD + behaviour-faithful to the reference (exact
world-view / deep-context strings pinned), over the `Repository` seam + ULID ids.
- **[AGENT] Ported LINK supporting cast into `core/assistant/`:** `world.py`
  (`build_world_view` — members + non-archived-done-included work items + events in
  a 7-day-back window, family-tz rendered; id tokens `[w:<id>]`/`[e:<id>]`/`[m:<id>]`
  = Option A), `linking.py` (`add_capturing_member_for_first_person`, pure),
  `deep.py` (`resolve_ids` + `deep_context` — the PROPOSE input: linked items +
  footprint-member assigned items + participated events, full update log/checklist,
  dedup). **`resolve_ids` now de-dups** (family-validate + dedup + first-seen order)
  — a deliberate fix over the reference's dup-leaking filter (LLD §3.1).
- **[AGENT] Two new repository reads** (LINK needs them; LLD §2.1):
  `list_work_items` (non-archived, done included) + `list_events` (all, full DTOs)
  on the protocol, `InMemoryRepository`, AND `DynamoRepository` (single base-table
  family-partition Query on `begins_with(SK, "WI#"|"EV#")`; `list_work_items`
  filters archived in Python). Tier-2 access-pattern tests added.
- **[AGENT] The `AnthropicClient` seam:** `core/assistant/anthropic_client.py` (a
  generic `create_message(system, messages, tools?, tool_choice?)` protocol, kept
  provider-generic per LLD §3.6), `tests/harness/anthropic_double.py`
  (`ScriptedAnthropicClient` + `link_response`/`propose_response`, real Messages
  shape — `content` list, `tool_use` blocks, `stop_reason`), and the real
  `adapters/anthropic_http.py` (`HttpAnthropicClient` — reads `{api_key,
  workspace_id}` from Secrets Manager, cached; stdlib `urllib` POST; the only place
  the Anthropic API is reached). The Converse-shaped `bedrock_double` is kept for
  the throwaway tracer (deleted Session 5); new `scripted_anthropic` conftest
  fixture (kept `scripted_bedrock`).
- **[AGENT] The LINK resolver:** `core/assistant/anthropic_link.py`
  (`AnthropicCaptureResolver.focus`) — world-view → forced `record_links` call →
  defensive parse of `tool_use.input` → first-person linking → `resolve_ids` →
  `deep_context` → `FocusedContext`. **Graceful-degrade:** any failure (API raise,
  missing `tool_use` block, malformed `input`) degrades the model's contribution
  to no-linked-ids and never raises; deterministic first-person linking still
  applies. System prompt trimmed ~50% for token efficiency (the forced tool
  carries the output-shape constraint). `FocusedContext` ids int→str (ULID ripple).
- **[AGENT] Tier-1 harness:** 5 world-view + 4 linking + 19 deep-context (incl. 11
  complex edges: dedup linked+assigned, linked+participated event dedup, author
  footprint, non-footprint exclusion, out-of-order update sort, empty-header
  omission, all-day+tags, start==end collapse, participant case/whitespace match +
  no false-match, resolve_ids dedup) + 9 LINK-resolver flow + 7 double tests.
  Deleted the stale skipped `test_placeholder.py`.
- **Gate GREEN (Tier 1):** `make check` — ruff + format + mypy clean, **262 passed /
  12 skipped, 99.07% core coverage** (≥95 gate).
- **Tier 2 GREEN (real `ntake-dev`, [HUMAN]-run):** `make integration` → **all
  passed** (23 tests). The two **live LINK calls** confirmed the whole seam against
  the real model: Secrets Manager `{api_key, workspace_id}` read, egress to
  `api.anthropic.com`, the forced-tool response shape, and **real Claude
  (`claude-haiku-4-5`) grounding** "the plumber is coming friday" → the in-family
  work item, and resolving nothing for an unrelated note. Surfaced + fixed one real
  bug (`DynamoRepository` missing the two new protocol methods → `isinstance`
  conformance failure), which is why the Dynamo impl landed this session rather than
  deferred.

### To-verify / deferred (open)
- **The BUG-001..008 hardening regression suite** (reference:
  `git show main:tests/assistant/test_local_llm_hardening.py`) is **Session 5** work
  — it exercises `propose()` (param-contract drops, BUG-002 local-weekday/time,
  UTC-leak drop, graceful-degrade). Recorded in AWS_PLAN Session 5.
- **PROPOSE's action/parameter split factoring** (LLD §3.6) applies when PROPOSE is
  built (Session 5): keep schema-projection / model-call / card-mapping separable so
  the future GENERATE⇒DECIDE swap is localized.
- `scripts/spike/` (the throwaway probe) can be deleted now it has served its purpose.

### Next session
**Session 5 — Assistant: PROPOSE tool-use + schema translation** (Phase 3b/3d).
Registry→Anthropic `tools`, `tool_choice:{type:any}` with `no_action`, ids as
enum-over-whitelist + app-side re-validation, `tool_use` block(s) → `ProposedAction`
cards (selection-not-execution, consume a list for parallel tool use), the
BUG-001..008 hardening suite, and the §3.6 action/parameter factoring. Tier-1-first
against the scripted double; the live PROPOSE call joins `make integration`. (See
AWS_PLAN Part II, Session 5.)


## Session 5 — Assistant: PROPOSE tool-use + schema translation  (done — Tier-1 green; Tier-2 live PROPOSE a [HUMAN] follow-up)
Built the whole PROPOSE stage, TDD + behaviour-faithful to the reference
(`git show main:app/assistant/local_llm/propose.py`), over the Session-4
`AnthropicClient` seam + the scripted double. Per the owner's steering, led with
the **behavioural flow test** (focused-context in → scripted `tool_use` out →
cards, nothing written) to pin the observable contract, then filled in the
implementation-detail unit tests (schema translation, the BUG-001..008 drops).
- **[AGENT] `core/assistant/anthropic_propose.py`** — `AnthropicAssistant`
  (`AssistantClient[FocusedContext]`), factored at the §3.6 action/parameter split
  into three separable pieces so the deferred GENERATE⇒DECIDE swap is localized:
  1. **action-space projection** — `build_tools_schema(registry, whitelists)`
     (pure): one Anthropic tool per `ActionSpec` (`name`/`description`/
     `input_schema`), `input_schema` assembled from `params` (required derived,
     `exclusive_params`→`oneOf`, `additionalProperties:false`), with the
     **per-request id-enum overlay** on `member_id` (= LINK's resolved member ids)
     and the **empty-whitelist tool-omission** rule (a required id param with an
     empty enum ⇒ omit the tool, so a degraded LINK lands on `no_action`/a
     no-target create rather than an unfillable tool);
  2. **the model call** — the one swappable unit behind `AnthropicClient`, with
     `tool_choice: {"type": "any"}` (MUST use a registered tool; `no_action` is a
     registered tool);
  3. **result mapping** — `_proposals_from` (pure): consume a **list** of
     `tool_use` blocks (parallel tool use, §3.5), drop-invalid (`spec.accepts` +
     `_has_valid_local_times` + **app-side id re-validation against the whitelist**
     + `needs_target`/target-attach), map each to a `ProposedAction`. **Selection,
     not execution** — never returns a `tool_result`, never loops, writes nothing
     (only the verb comes from the model; the concrete `target_id`/`target_type` is
     attached by the app from LINK's resolved ids). **Graceful-degrade:** any
     failure (API raise, missing blocks, malformed `input`) → `[]`, never raises.
  Reuses `build_tools_view` is NOT reused (the prose view is replaced by the
  `tools` schema); reuses the registry (`REGISTRY`/`DataType.json_schema`),
  `FocusedContext` primaries, and `validate_family_local_datetime`.
  System prompt is short/token-efficient (the tool schemas carry the shape
  constraint). v1 builds **no** separate param-generator/decision interface (the
  §3.6 refactor is YAGNI until then — only piece 2 changes under it).
- **[AGENT] Engine `ProposedAction.target_id` loosened `int | None` → `str | None`**
  (owner-confirmed): the reference predated the ULID ripple; ids are ULID strings
  app-wide (matches `ProposalRead.target_id: str | None`). Dead int path dropped
  (not `str | int | None`). One-line change + docstring note; the engine stays
  domain-neutral (id value opaque).
- **[AGENT] Tier-1 harness (led with behaviour):**
  `tests/assistant/test_propose_resolver.py` (15 flow tests — the contract:
  tool_choice=any + registry projection sent; map-without-executing (repo
  untouched); single `create_message` call / no loop / no tool_result; `no_action`
  a normal selection; **multiple blocks → multiple cards**; work-item/event target
  attach from resolved ids; target-needing-action-without-id dropped;
  fabricated-member-id dropped vs whitelist; whitelisted survives; graceful-degrade
  (raise/missing-content/malformed-input/unknown-action → `[]`); valid survives
  alongside invalid). Then the implementation-detail units:
  `test_propose_schema.py` (7 — projection internals: one-tool-per-action,
  required derived, datatype fragments, `oneOf`, member-id enum overlay,
  empty-whitelist omission) and `test_propose_hardening.py` (BUG-001..008 port vs
  the Anthropic double: missing/empty required param; timed action missing a time;
  **BUG-002** keep well-formed local vs drop UTC-`Z`/wrong-shape/non-string;
  valid-alongside-invalid; malformed-envelope degrade). Owner-confirmed scope: the
  reference's *transport*-level drops (4xx/5xx/timeout/non-JSON→`{}`) are NOT
  re-expressed — that boundary now lives in the resolver's blanket `except` (as
  LINK), and `HttpAnthropicClient` is Tier-2-only.
- **[AGENT] Tier 2 wired (not run this sitting):**
  `tests/integration/test_propose_live.py` — two live PROPOSE calls against the
  real Anthropic API (reuses the deployed `{api_key, workspace_id}` secret; **no
  Bedrock gate**), self-skipping if the secret is unset (never a false pass),
  mirroring `test_link_live.py`. Lands in `tests/integration/`, which
  `scripts/integration.sh` already runs, so **no Makefile/script change needed** to
  "extend `make integration`". Suite collects **25 tests without AWS** (2 new live
  PROPOSE + the existing 23).
- **[AGENT] Tier-2 suite consolidated to happy-path + irreducible contracts
  (owner-requested).** Collapsed Tier 2 from **25 tests to 6**, on the principle:
  if the in-memory double can give a trustworthy answer, the assertion is boundary
  logic and belongs at Tier 1 (fast, exact); only properties where in-memory and
  DynamoDB can *disagree* stay at Tier 2. Verified first that
  `tests/data/test_repository_flows.py` **already** covers every boundary-logic
  case backend-agnostically (archived-exclusion, board grouping/ordering, family
  scoping, calendar unify/range, due-bridge set/clear, all-day timezone,
  co-created pair outcome) — so nothing was lost by removing the Tier-2 re-runs.
  - **Deleted** `tests/integration/test_dynamo_flows.py` (all 7 bodies re-ran
    strongly-consistent base-table logic already proven at Tier 1; the transaction
    case is also asserted natively below).
  - **Deleted** `test_link_live.py` (real LINK over *in-memory* — half-integrated)
    and `test_propose_live.py` (real PROPOSE over a *stubbed* `(none linked)`
    context with empty whitelists — the gap the owner caught). Both are subsumed by
    the joint pipeline test.
  - **Trimmed** `test_dynamo_access_patterns.py` from 14 → **5 irreducible
    contracts**: the co-created `TransactWriteItems` (both sides land; the home of
    the double-serialization + `list_append` operand-type bugs), the single-`Put`
    standalone create (write-primitive spy), the two **raw-GSI** key-shape +
    sparse-drop assertions (GSI1 `STATUS#…#POS#…`, GSI2 `TS#…#EV#`/`TS#…#WI#`), and
    **one** representative GSI eventual-consistency drop-out through the repo read
    (archive → leaves calendar). Dropped the 9 that re-assert Tier-1-covered
    semantics (board grouping, done-list, calendar unify/range, due set/clear,
    all-day, delete-event, family-scoping, the two base-table list_* reads).
  - **Result:** Tier 2 = **2 happy-path assistant pipeline tests
    (`test_capture_pipeline_live.py`) + 5 Dynamo-only contracts**. The true
    full-stack e2e (HTTP→auth→Lambda→publish→Dynamo→model) remains the Session-8
    sweep, after Session 6 builds the handlers. Suite collects **7 tests without
    AWS**.
- **[AGENT] §3.5 multi-tool-call signal (owner-requested, observe-not-assert).**
  Added `test_live_multi_intent_note_tool_call_signal` to the pipeline module: a
  genuinely multi-intent note ("call the plumber about friday **and** add milk to
  the grocery list" — two independent intents over two seeded targets) runs the
  real LINK→PROPOSE pipeline, and the resulting **card count + names are recorded**
  (`record_property` + a printed `[§3.5 multi-tool-call signal]` line) so the
  Session-8 full-tool-count reconciliation has real data. The count is
  **deliberately NOT asserted** — whether real Claude fans out vs. prefers one is
  the open §3.5 question; the design consumes a *list* of `tool_use` blocks either
  way (reshape-free), so only the invariant contract is asserted (≥1 card, every
  card a registered action).
- **Gate GREEN (Tier 1):** `make check` — ruff lint+format clean, mypy clean (84
  source files), **295 passed / 12 skipped, 99.15% core coverage** (≥95 gate);
  `core/assistant/anthropic_propose.py` **100%**. (Baseline at session start: 262
  passed; +33 new tests.)

### To-verify / deferred (open)
- **Tier-2 live PROPOSE run is a [HUMAN] follow-up:** run `make integration`
  (key is set; no Bedrock gate) to confirm registry→`tools` + `tool_choice:any`
  are accepted by the real Messages API, the model returns `tool_use` block(s),
  enum-over-whitelist holds, and the **multi-tool-call** behaviour (§3.5 — does
  real Claude emit multiple tool calls for a multi-intent note, or prefer one?) at
  the current tool count. Reconciled at full tool count in Session 8.
- **Tracer teardown is its own step (owner-confirmed, NOT this session):** delete
  the throwaway `tracer/`, `TracerStack`, `tests/harness/bedrock_double.py` +
  `scripted_bedrock` fixture + `tests/assistant/test_tracer_bedrock.py`, the
  bedrock/tracer probe scripts (`bedrock_bisect.py`/`bedrock_preflight.py`/
  `nova_probe.py`/`tracer_validate.py`/`ws_check.py`), and repoint `make
  deploy-dev` at `NtakeStack-dev`. Mechanical, touches CDK/infra — kept out of the
  PROPOSE session to isolate risk. (`scripts/spike/` is already gone.)
- `core/assistant/anthropic_link.py` + `world.py` residual partial branches
  (94%/97%) are unchanged from Session 4 — well over the 95 gate; left as-is.

### Next session
**Session 6 — Thin handlers + authorizer + confirm/execute + live-sync publish**
(Phase 4). The HTTP/auth surface + the execute→publish boundary: drive each route
through its thin handler over the in-memory repo + scripted Anthropic seam
(health, reads, `/capture` propose-only writes-nothing, `/actions/confirm`
executes via the registry + publishes once), the single-publish-boundary
invariant test, the authorizer (HMAC→member) + minting, and the HTTP/WS API +
per-Lambda roles into `NtakeStack`. (See AWS_PLAN Part II, Session 6.)


## Tracer teardown  (done — its own commit, after Session 5)
Deleted the throwaway Session-1.5 tracer slice now that all three things it was
built to de-risk are resolved: IAM/authorizer-context pass (proven; rebuilt
properly in Session 6), WebSocket connect/routing (proven; delivery deferred to
the Session-6 execute boundary), and the Bedrock multi-tool-call question (**moot**
— the project pivoted off Bedrock to the Anthropic API, AWS_LLD §3.5/§10). The
tracer was pure dead weight: a deployed `TracerStack-dev`, a `tracer/` package,
two tracer tests on the Tier-1 gate, the Converse-shaped `bedrock_double` only it
used, and five Bedrock/tracer probe scripts.
- **Deleted (code):** the whole `tracer/` package (`__init__`, `app_handler`,
  `authorizer`, `bedrock_tracer`, `ws_handler`); `infra/lib/tracer-stack.ts`
  (+ compiled `.js`/`.d.ts`); `tests/harness/bedrock_double.py`;
  `tests/api/test_tracer_authorizer.py`, `tests/api/test_tracer_http_ws.py`,
  `tests/assistant/test_tracer_bedrock.py`; the probe scripts
  `scripts/{bedrock_bisect,bedrock_preflight,nova_probe,tracer_validate,ws_check}.py`.
- **Edited (rewire):** `infra/bin/ntake-aws.ts` drops the `TracerStack` import +
  instantiation (now only `NtakeStack-dev`/`-prod`); `tests/conftest.py` drops the
  `scripted_bedrock` fixture + `ScriptedBedrockClient` import (keeps
  `scripted_anthropic`); `tests/test_harness.py` drops the Bedrock-double
  self-tests (the Anthropic double has its own suite); `tests/harness/__init__.py`
  + `anthropic_double.py` docstrings drop the stale `bedrock_double` references;
  `tests/api/test_placeholder.py` docstring "scripted Bedrock" → "scripted
  Anthropic seam".
- **Makefile:** removed `tracer` from the lint/mypy `SRC` paths; removed the
  `bedrock-preflight` target; **repointed `make deploy-dev` at `NtakeStack-dev`**
  (was `cdk deploy TracerStack-dev`) — the real dev stack, consistent with
  `make integration DEPLOY=1`.
- **[HUMAN] follow-up — destroy the deployed tracer:** `TracerStack-dev` is still
  live on `111037110464`. Run **`cd infra && npm run build && cdk destroy
  TracerStack-dev`** (dev-only; never touches `NtakeStack`/prod) to remove its
  table + secret + 5 Lambdas + the HTTP/WS APIs. The code is gone so it will never
  be re-synthesized/redeployed; the destroy just reclaims the deployed resources.
- **Gate GREEN:** `make check` — ruff + mypy + format clean, **268 passed / 12
  skipped, 99.15% core coverage** (−27 tests vs Session 5's 295 = the removed
  tracer/bedrock-double self-tests; core coverage unchanged — the tracer was never
  in the `core` coverage target). **`make synth` clean** — only
  `NtakeStack-dev`/`-prod` synthesize; no `TracerStack`.
