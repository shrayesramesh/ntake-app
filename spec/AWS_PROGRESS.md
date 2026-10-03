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
