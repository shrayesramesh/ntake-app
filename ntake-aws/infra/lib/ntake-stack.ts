import { Stack, StackProps, RemovalPolicy, CfnOutput } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

/**
 * Per-stage typed props (AWS_LLD §7.2). Declared in Session 1; Sessions 3/5/7
 * extend this one shape rather than inventing stage branching. Session 3 is the
 * first to consume them — `removalPolicy` + `pointInTimeRecovery` now drive the
 * single table's dev-vs-prod lifecycle.
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
 * The single stack, instantiated per stage.
 *
 * Session 3 lands the FIRST real resource: the DynamoDB single table
 * `ntake-<stage>` with its two GSIs (AWS_LLD §1) — pulled forward from §5a so
 * there is a real table to integrate `DynamoRepository` against via
 * `make integration`. The remaining resources — HTTP + WebSocket APIs, Lambdas
 * with scoped IAM, CloudFront, the two S3 buckets, Secrets Manager, the Budgets
 * alarm — arrive in Sessions 6/7 (AWS_HLD §3, AWS_LLD §7), building on this
 * table. The throwaway TracerStack (Session 1.5) remains separate and untouched
 * until Session 5 deletes it.
 */
export class NtakeStack extends Stack {
  /** The single table name, exported so handlers' env + IAM grants (Sessions 6/7) reference one source. */
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: NtakeStageProps) {
    super(scope, id, props);

    // --- DynamoDB single table (AWS_LLD §1.1) --------------------------------
    // PK/SK are type-prefixed strings (FAM#/WI#/EV#/MEM#/CONN#/TOK#); every
    // access pattern is one op on this table or one of its two sparse GSIs.
    // On-demand billing (no capacity planning at household scale). The TTL
    // attribute is RESERVED now (declared, nothing writes it in v1) so enabling
    // expiry later needs no table replacement.
    this.table = new dynamodb.Table(this, "NtakeTable", {
      tableName: `ntake-${props.stage}`,
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: props.removalPolicy, // dev: DESTROY; prod: RETAIN
      pointInTimeRecovery: props.pointInTimeRecovery, // prod replaces the old weekly snapshot
      timeToLiveAttribute: "ttl", // reserved; nothing sets it in v1 (AWS_LLD §7.1)
    });

    // GSI1 — the board (AWS_LLD §1.2). GSI1PK = FAM#<fam>#BOARD,
    // GSI1SK = STATUS#<status>#POS#<zero-padded>. SPARSE: the repository writes
    // the GSI1 keys only when `archived_at` is null, so archiving an item drops
    // it from the board index with no delete. One Query returns the four
    // columns pre-sorted by status then position.
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI1",
      partitionKey: { name: "GSI1PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI1SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI2 — the calendar (AWS_LLD §1.2). GSI2PK = FAM#<fam>#CAL,
    // GSI2SK = TS#<sort_ts>#<EV#id | WI#id>. SPARSE: set on timed/all-day events
    // and on due-dated (unarchived) work items (the calendar/due-date bridge), so
    // one range Query returns events + due items in a single time-ordered pass.
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI2",
      partitionKey: { name: "GSI2PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI2SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // The integration harness (make integration) reads the table name to point
    // DynamoRepository at the deployed table.
    new CfnOutput(this, "TableName", { value: this.table.tableName });
  }
}
