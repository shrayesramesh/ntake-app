#!/usr/bin/env node
import { App, RemovalPolicy } from "aws-cdk-lib";
import { NtakeStack, NtakeStageProps } from "../lib/ntake-stack.js";
import { TracerStack } from "../lib/tracer-stack.js";

// Pinned account + region (AWS_LLD header; AWS_PLAN Phase 0). Session 1 does NOT
// deploy — `cdk synth` only. The env is set so synth produces a stage-correct
// template; no credentials or AWS calls happen at synth time.
const env = { account: "111037110464", region: "us-east-1" } as const;

const dev: NtakeStageProps = {
  env,
  stage: "dev",
  // Claude Haiku 4.5 via its US cross-region INFERENCE PROFILE id. Modern Claude
  // models on Bedrock are inference-profile-only (no bare ON_DEMAND id). Chosen
  // over Nova because the PROPOSE design is built on Claude-style Converse
  // tool-use + toolChoice (Nova rejected the tool-use call in Session 1.5).
  // Cheapest current Claude; "small model is the cost dial" (AWS_HLD §7a).
  bedrockModelId: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  bedrockLogFidelity: "full",
  apiThrottle: { rateLimit: 20, burstLimit: 40 },
  removalPolicy: RemovalPolicy.DESTROY,
  pointInTimeRecovery: false,
  budgetUsd: 25,
};

const prod: NtakeStageProps = {
  env,
  stage: "prod",
  bedrockModelId: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  bedrockLogFidelity: "full",
  apiThrottle: { rateLimit: 10, burstLimit: 20 },
  removalPolicy: RemovalPolicy.RETAIN,
  pointInTimeRecovery: true,
  budgetUsd: 25,
};

const app = new App();
new NtakeStack(app, "NtakeStack-dev", dev);
new NtakeStack(app, "NtakeStack-prod", prod);

// ⚠️ THROWAWAY tracer-bullet slice (AWS_PLAN Session 1.5) — a SEPARATE stack,
// dev-only, deleted when Session 5 builds the real resources into NtakeStack.
// Deployed with `make deploy-dev` → `cdk deploy TracerStack-dev` (the [HUMAN]
// step). Kept apart from NtakeStack so removing the scaffolding can never
// disturb the real stack. No prod tracer.
new TracerStack(app, "TracerStack-dev", {
  env,
  bedrockModelId: dev.bedrockModelId,
});

app.synth();
