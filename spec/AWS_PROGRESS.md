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

