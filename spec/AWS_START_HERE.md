# AWS Rebuild — START HERE

You are working on the **from-scratch, AWS-native rebuild** of the family
calendar + work-item app (serverless: CloudFront + API Gateway + Lambda +
DynamoDB + Bedrock). This is the active direction. The self-hosted app
(`AGENT_START_HERE.md`, `DESIGN.md`, `PLAN.md`) is the **current `mainline`** and
is reference-only for this effort — do not follow it as the build plan.

## Read in this order
1. **[`AWS_HLD.md`](AWS_HLD.md)** — architecture + the agreed decisions. Start with
   §2 (decisions) and §2a (the three accepted posture tradeoffs vs. the original
   requirements).
2. **[`AWS_LLD.md`](AWS_LLD.md)** — concrete design: single-table schema (§1),
   repository (§2), the two Bedrock seams (§3), live sync (§4), identity (§5),
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

## The one open risk (don't be surprised)
**Bedrock multi-tool-call per Converse turn is unverified** (does one PROPOSE call
return multiple `toolUse` blocks → multiple proposal cards?). It is resolved
**early, in Session 1.5** (the tracer-bullet dev deploy), before the local
sessions build on it. If it resolves the "one call per turn" way, the fallback
(loop or one-proposal-per-capture) is a call-count change, not a reshape
(LLD §3.5). Cold-start latency on the 30s capture path is accepted-but-unmeasured.

## State / resume
Each session appends a hand-off note (commit body or `spec/AWS_PROGRESS.md`): what
landed, gate summary, to-verify opened/closed, the next session. A fresh context
resumes from there.
