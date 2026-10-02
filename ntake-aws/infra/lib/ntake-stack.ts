import { Stack, StackProps, RemovalPolicy } from "aws-cdk-lib";
import { Construct } from "constructs";

/**
 * Per-stage typed props (AWS_LLD §7.2). Declared now so Sessions 5/7 extend
 * this one shape rather than inventing stage branching. Session 1 synthesizes
 * an EMPTY stack — no resources yet — proving the infra compiles and both
 * stages synth cleanly before any resource lands.
 */
export interface NtakeStageProps extends StackProps {
  readonly stage: "dev" | "prod";
  readonly bedrockModelId: string; // small model is the cost dial (Haiku/Nova)
  readonly bedrockLogFidelity: "full" | "metadata"; // default "full"
  readonly apiThrottle: { readonly rateLimit: number; readonly burstLimit: number };
  readonly removalPolicy: RemovalPolicy; // dev: DESTROY; prod: RETAIN
  readonly pointInTimeRecovery: boolean; // dev: false; prod: true
  readonly budgetUsd: number;
}

/**
 * The single stack, instantiated per stage. EMPTY in Session 1 (walking
 * skeleton for the gate). The real resources — DynamoDB single table + 2 GSIs,
 * HTTP + WebSocket APIs, Lambdas with scoped IAM, CloudFront, the two S3
 * buckets, Secrets Manager, the Budgets alarm — are added in Sessions 1.5/5/7
 * (AWS_HLD §3, AWS_LLD §7).
 */
export class NtakeStack extends Stack {
  constructor(scope: Construct, id: string, props: NtakeStageProps) {
    super(scope, id, props);
    // Intentionally empty in Session 1. `props` is accepted so the per-stage
    // wiring is exercised by `cdk synth`; resources arrive in later sessions.
    void props.stage;
  }
}
