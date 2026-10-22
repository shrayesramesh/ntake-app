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
  // Assistant LLM: the Anthropic API (Claude), called directly over HTTPS with an
  // API key from Secrets Manager — NOT Bedrock (account-level Bedrock invocation
  // hold; see AWS_HLD decision §10 / AWS_LLD §3.5 for why the pivot). Model is
  // just a string in the Messages request body; "small model is the cost dial"
  // (AWS_HLD §7a). Pin a current Haiku-class id when the seam is built (Session 4).
  anthropicModelId: "claude-haiku-4-5",
  assistantLogFidelity: "full",
  apiThrottle: { rateLimit: 20, burstLimit: 40 },
  removalPolicy: RemovalPolicy.DESTROY,
  pointInTimeRecovery: false,
  budgetUsd: 25,
};

const prod: NtakeStageProps = {
  env,
  stage: "prod",
  anthropicModelId: "claude-haiku-4-5",
  assistantLogFidelity: "full",
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
  // The tracer genuinely probes Bedrock (that is what it was built to de-risk),
  // so it keeps the Bedrock inference-profile id regardless of the NtakeStack
  // pivot to the Anthropic API. Throwaway; deleted in Session 5.
  bedrockModelId: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
});

app.synth();
