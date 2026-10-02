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

### Next session
**Session 1 — Skeleton + gate + test harness + tooling** (Phase 1). Sessions 0.1
and 0.2 are complete; the account is bootstrapped. Session 1 stands up the
`ntake-aws` package shape (`infra/`, `handlers/`, `adapters/`, `core/` already
seeded, `tests/`), the `Makefile` + `scripts/` tooling, pinned deps, ruff/mypy/
pytest config, the boundary test, the shared test harness, and `make synth` on a
minimal empty CDK stack — ending at a green `make check`.
