# Session 7 — Complete the stack: logging + CloudFront/S3 + Budgets + prod props

You are continuing the from-scratch AWS-native rebuild of the family calendar +
work-item app. Work in `/Users/shrayesr/kiroprojects/ntake-app` on the
`aws-rebuild` branch. The app lives in `ntake-aws/`, specs in `spec/`.

## Read first, in order
1. `spec/AWS_START_HERE.md` — how to work.
2. `spec/AWS_PROGRESS.md` — the resume log. Pick up from the **Session 6** notes
   at the bottom (including "first-deploy fix" and "CLOSED").
3. `spec/AWS_PLAN.md` — the **Operating rules** (note the newer ones: Lambda code
   is stdlib + runtime `boto3` only with no bundling; no env-var switches for
   build/test behavior) and Part II **"Session 7"** — the goal + exit criteria.
4. `spec/AWS_LLD.md` §6 (assistant logging → S3), §7 (CDK stack + per-stage
   props), §8 (test tiers).

## Where things stand (decided and committed — don't re-litigate)
- Session 6 is closed: `make check` 355 passed (98.71% core), 13 infra
  assertions; `make integration` 12/12 green on `ntake-dev`, including the live
  write → publish → WebSocket nudge through the real authorizer.
- `NtakeStack` already has: the table + GSIs, the Anthropic + token secrets
  (created empty, values set out-of-band), 8 role-grouped Lambdas (1024 MB /
  10 s defaults in `makeFn`; capture 30 s), the HTTP API + authorizer, and the
  WebSocket API. Session 7 adds the remaining resources on top — don't rebuild
  what exists.
- Enrollment is the 6-digit pairing-code exchange (not the old `/enroll#token=`
  URL); the frontend may be rebuilt, so build the static-hosting infra the plan
  specifies without coupling it to a particular client.

## Steers from the owner (not recorded elsewhere)
- **Stick to the plan as written.** Don't trim or reshape a session's scope on
  your own; if something in the plan looks wrong, raise it and wait.
- **Confirm scope and design decisions before acting** — present options with a
  recommendation, then build what the owner picks.
- **YAGNI + DRY.** Smallest correct change; one source of truth; no speculative
  helpers, tables, or knobs. Prefer explicit code over clever generic machinery.
- **Integration-style behavior tests first**, then implementation-detail tests.
- Private family app on a private account: keep cheap correctness safeguards,
  skip high-traffic-service hardening ceremony.

## Deploy notes (learned in Session 6)
- Everything the deploy creates empty (e.g. a new secret) must be deployed
  *before* its out-of-band value can be set — sequence [HUMAN] steps as
  deploy → set value → test.
- Renaming a CDK construct replaces the resource (and its IAM role); CDK will
  then prompt for security-change approval. Flag that before the owner deploys.
- Cloud-only bugs (packaging, API Gateway response shapes, Lambda sizing) only
  show up at Tier 2 — wire a real `make integration` path for what you build and
  have it self-skip, never fake-pass, on unmet preconditions.

## Operating rules
- TDD: test first, watch it fail, then implement. `make check` must be green with
  real pasted output before you claim done. `make synth` + infra assertions too.
- `make integration` / `make deploy-dev` are **[HUMAN]-invoked** — build and
  surface the commands; never put the account's creds in your environment.
- At the end: append a **Session 7 hand-off note** to `spec/AWS_PROGRESS.md`,
  commit at each green gate (conventional commits), replace this file with a
  `SESSION8_PROMPT.md`, and do **NOT** `git push`.

## Start
Read the docs above and `ntake-aws/infra/lib/ntake-stack.ts`, then **propose your
Session 7 plan (scope, design choices with a recommendation, TDD order) before
writing code.**
