# AWS Rebuild — START HERE

You are working on the **from-scratch, AWS-native rebuild** of the family
calendar + work-item app (serverless: CloudFront + API Gateway + Lambda +
DynamoDB, with the assistant on the Anthropic API). This is the active direction. The self-hosted app
(`AGENT_START_HERE.md`, `DESIGN.md`, `PLAN.md`) is the **current `mainline`** and
is reference-only for this effort — do not follow it as the build plan.

## Read in this order
1. **[`AWS_HLD.md`](AWS_HLD.md)** — architecture + the agreed decisions. Start with
   §2 (decisions) and §2a (the three accepted posture tradeoffs vs. the original
   requirements).
2. **[`AWS_LLD.md`](AWS_LLD.md)** — concrete design: single-table schema (§1),
   repository (§2), the two Anthropic-API seams (§3), live sync (§4), identity (§5),
   logging (§6), CDK (§7), tests (§8), frontend (§9).
3. **[`AWS_PLAN.md`](AWS_PLAN.md)** — the build. **Part I** = phases; **Part II** =
   the step-by-step **agent sessions** you actually execute. The Git-strategy
   section (branch, lift map, replace-mainline) comes first.
4. **[`REQUIREMENTS.md`](REQUIREMENTS.md)** — functional requirements are unchanged
   records-of-record; **§5a** has the AWS-revised NFRs.

## How to work
- **Run one Part-II session per sitting**, in order, starting at **Session 0**
  (branch + account preflight). Each session has explicit Goal + Exit criteria;
  stop at Exit, run the gate, commit, write the hand-off note.
- **TDD, integration-first; DRY.** Gate (`make check`) must be green before a
  session is done — paste real output, never claim green without running it.
- **`[HUMAN]` steps** (the two AWS console actions, each `cdk deploy`, device
  tests) are the owner's — stop and ask; never touch the AWS console/credentials.
- Account `111037110464`, region `us-east-1`. App = Python; infra/CDK = TypeScript.

## Known open items (don't be surprised)
- **Multi-tool-call** — resolved by the Anthropic pivot: the Messages API returns
  parallel `tool_use` blocks natively, and the live Tier-2 signal test shows the
  model fanning a two-intent note into 2 cards. Full-tool-count reconciliation is
  Session 8 (LLD §3.5).
- **Cold-start latency** — Lambdas are sized at 1024 MB / 10 s (capture 30 s)
  after the Session-6 authorizer timeout; the 30 s capture budget is still
  accepted-but-unmeasured end to end.

## State / resume
Each session appends a hand-off note to `spec/AWS_PROGRESS.md`: what landed, gate
summary, to-verify opened/closed, the next session. The current session's
kickoff prompt is `spec/SESSION<N>_PROMPT.md` (one at a time — each session
replaces it with the next). A fresh context resumes from those two.
