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

