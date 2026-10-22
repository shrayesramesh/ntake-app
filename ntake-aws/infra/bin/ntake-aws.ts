#!/usr/bin/env node
import { App, RemovalPolicy } from "aws-cdk-lib";
import { NtakeStack, NtakeStageProps } from "../lib/ntake-stack.js";

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

app.synth();
