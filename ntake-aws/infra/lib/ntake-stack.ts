import { Stack, StackProps, RemovalPolicy, CfnOutput, Duration } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as path from "node:path";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { WebSocketLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import {
  HttpLambdaAuthorizer,
  HttpLambdaResponseType,
} from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import { WebSocketLambdaAuthorizer } from "aws-cdk-lib/aws-apigatewayv2-authorizers";

/**
 * Per-stage typed props (AWS_LLD §7.2). Declared in Session 1; Sessions 3/5/7
 * extend this one shape rather than inventing stage branching. Session 3 is the
 * first to consume them — `removalPolicy` + `pointInTimeRecovery` now drive the
 * single table's dev-vs-prod lifecycle. Session 6 consumes `apiThrottle` (the
 * HTTP stage default route settings) and `removalPolicy` (the new token secret).
 */
export interface NtakeStageProps extends StackProps {
  readonly stage: "dev" | "prod";
  readonly anthropicModelId: string; // Claude model string for the Messages API; small = the cost dial
  readonly assistantLogFidelity: "full" | "metadata"; // default "full"
  readonly apiThrottle: { readonly rateLimit: number; readonly burstLimit: number };
  readonly removalPolicy: RemovalPolicy; // dev: DESTROY; prod: RETAIN
  readonly pointInTimeRecovery: boolean; // dev: false; prod: true
  readonly budgetUsd: number;
}

// The Lambda code asset is the ntake-aws package ROOT (two levels up from
// infra/lib/), so `core/`, `adapters/`, and `handlers/` are all importable and
// each function sets `handler = "handlers.<module>.<fn>"`. The compiled output
// is CommonJS (no `"type": "module"` in infra/package.json), so `__dirname` is
// the ambient CommonJS global — resolved relative to infra/lib/.
const LAMBDA_ASSET_ROOT = path.join(__dirname, "..", "..");

/**
 * The single stack, instantiated per stage.
 *
 * Session 3 landed the DynamoDB single table + the empty Anthropic secret.
 * **Session 6** (this slice, AWS_HLD §3 / AWS_LLD §7) lands the request path:
 * the HMAC token secret, nine per-route Lambdas with tightly-scoped IAM
 * (design B — one role per function, construct-scoped grants, never a wildcard),
 * the HTTP API with a simple-response Lambda authorizer, and the WebSocket API
 * (`$connect`/`$disconnect`) for server→client nudges. CloudFront, the S3
 * buckets, and the Budgets alarm remain Session 7.
 *
 * The **Anthropic API key secret** (Session 3) and the **token secret**
 * (Session 6) are both created EMPTY: CDK owns name/ARN/removal-policy; the
 * values are set out-of-band via `aws secretsmanager put-secret-value` (a
 * [HUMAN] step), so no secret value ever enters the repo, the template, or
 * CloudFormation state. The Lambdas that need them get a construct-scoped
 * `secret.grantRead(fn)` — not an ARN wildcard.
 */
export class NtakeStack extends Stack {
  /** The single table name, exported so handlers' env + IAM grants reference one source. */
  public readonly table: dynamodb.Table;

  /**
   * The Anthropic API key secret (created EMPTY — value set out-of-band via
   * `put-secret-value`, see scripts/secrets-anthropic.sh). The capture Lambda
   * `grantRead`s on it and reads its ARN at cold start.
   */
  public readonly anthropicApiKeySecret: secretsmanager.Secret;

  /**
   * The HMAC device-token secret (AWS_LLD §5.1), created EMPTY. The authorizer
   * and the pair exchange hash presented tokens under this secret; both Lambdas
   * get a construct-scoped `grantRead`.
   */
  public readonly tokenSecret: secretsmanager.Secret;

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

    // --- Secrets Manager: the Anthropic API key (AWS_LLD §7.1) ---------------
    // Created EMPTY. CDK owns the secret's name/ARN/removal-policy ONLY; the key
    // VALUE is NEVER in code, the template, or CloudFormation state — it is set
    // out-of-band via `aws secretsmanager put-secret-value`
    // (scripts/secrets-anthropic.sh), a [HUMAN] step. The capture Lambda is
    // granted `secretsmanager:GetSecretValue` on THIS secret's ARN (below) and
    // reads the key at cold start. Replaces the Bedrock path (AWS_HLD §10).
    this.anthropicApiKeySecret = new secretsmanager.Secret(this, "AnthropicApiKey", {
      secretName: `ntake-${props.stage}/anthropic-api-key`,
      description:
        "Anthropic API key for the capture assistant (LINK + PROPOSE). " +
        "Value set out-of-band via scripts/secrets-anthropic.sh — never in CDK.",
      removalPolicy: props.removalPolicy, // dev: DESTROY; prod: RETAIN
    });

    new CfnOutput(this, "AnthropicApiKeySecretArn", {
      value: this.anthropicApiKeySecret.secretArn,
    });

    // --- Secrets Manager: the HMAC device-token secret (AWS_LLD §5.1) --------
    // Same empty-secret pattern as the Anthropic key. The authorizer and the
    // pair exchange read it (via `grantRead` below) to verify/mint device
    // tokens; the value is set out-of-band, never in CDK/template/state.
    this.tokenSecret = new secretsmanager.Secret(this, "TokenSecret", {
      secretName: `ntake-${props.stage}/token-secret`,
      description:
        "HMAC device-token secret (authorizer + pair exchange, AWS_LLD §5.1). " +
        "Value set out-of-band — never in CDK.",
      removalPolicy: props.removalPolicy, // dev: DESTROY; prod: RETAIN
    });

    // --- Lambda functions (design B: per-route, scoped IAM) ------------------
    // One asset for all nine functions (the ntake-aws root); each function
    // differs only by its `handler` entry point, env, timeout, and IAM grants.
    // Grants are applied via construct methods (table.grantReadData /
    // grantReadWriteData, secret.grantRead, wsApi.grantManageConnections) so the
    // synthesized policies are scoped to the exact resource ARN — never "*".
    const code = lambda.Code.fromAsset(LAMBDA_ASSET_ROOT, {
      exclude: [
        "infra/cdk.out",
        "infra/node_modules",
        ".venv",
        "**/__pycache__",
        "**/*.pyc",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "tests",
      ],
    });
    const region = Stack.of(this).region;
    const baseEnv = {
      NTAKE_TABLE_NAME: this.table.tableName,
      NTAKE_REGION: region,
    };

    const makeFn = (
      id: string,
      handler: string,
      opts: { timeout?: Duration; environment?: Record<string, string> } = {},
    ): lambda.Function =>
      new lambda.Function(this, id, {
        runtime: lambda.Runtime.PYTHON_3_12,
        code,
        handler,
        timeout: opts.timeout,
        environment: { ...baseEnv, ...(opts.environment ?? {}) },
      });

    // authorizer — reads TOK# items + the token secret only. No write, no GSI.
    const authorizerFn = makeFn("AuthorizerFn", "handlers.authorizer.handler", {
      environment: { NTAKE_TOKEN_SECRET_ID: this.tokenSecret.secretName },
    });
    this.table.grantReadData(authorizerFn); // GetItem on TOK# items
    this.tokenSecret.grantRead(authorizerFn); // GetSecretValue on the token secret

    // reads — GET routes; read-only on the table + GSIs. Default (short) timeout.
    const readsFn = makeFn("ReadsFn", "handlers.http_api.reads_handler");
    this.table.grantReadData(readsFn); // GetItem/Query on table + GSIs; NO writes

    // capture — LINK→PROPOSE (two Anthropic calls). Reads the table + the
    // Anthropic secret only; NO bedrock anywhere. 30s timeout for the calls +
    // cold start.
    const captureFn = makeFn("CaptureFn", "handlers.http_api.capture_handler", {
      timeout: Duration.seconds(30),
      environment: {
        NTAKE_ANTHROPIC_MODEL: props.anthropicModelId,
        NTAKE_ANTHROPIC_SECRET_ID: this.anthropicApiKeySecret.secretName,
      },
    });
    this.table.grantReadData(captureFn);
    this.anthropicApiKeySecret.grantRead(captureFn); // GetSecretValue on the Anthropic secret only

    // pairing — an enrolled member mints a pairing code (PutItem PAIR#).
    const pairingFn = makeFn("PairingFn", "handlers.http_api.pairing_handler");
    this.table.grantWriteData(pairingFn); // PutItem on PAIR# items

    // pair — PUBLIC: redeem a code → device token (read PAIR#, write TOK#),
    // signing with the token secret.
    const pairFn = makeFn("PairFn", "handlers.http_api.pair_handler", {
      environment: { NTAKE_TOKEN_SECRET_ID: this.tokenSecret.secretName },
    });
    this.table.grantReadWriteData(pairFn); // read PAIR#, write TOK#
    this.tokenSecret.grantRead(pairFn);

    // WebSocket connect/disconnect — write CONN# items only.
    const wsConnectFn = makeFn("WsConnectFn", "handlers.ws.connect_handler");
    this.table.grantWriteData(wsConnectFn);
    const wsDisconnectFn = makeFn("WsDisconnectFn", "handlers.ws.disconnect_handler");
    this.table.grantWriteData(wsDisconnectFn);

    // --- WebSocket API (AWS_LLD §4.1) ----------------------------------------
    // Server→client nudges only (the client refetches; it never sends on the
    // socket), so only $connect/$disconnect. $connect uses the SAME REQUEST
    // authorizer, with the token read from `?token=` (WS authorizers cannot read
    // a Bearer header — identity source is the querystring).
    const wsAuthorizer = new WebSocketLambdaAuthorizer("WsAuthorizer", authorizerFn, {
      identitySource: ["route.request.querystring.token"],
    });

    const wsApi = new apigwv2.WebSocketApi(this, "WsApi", {
      apiName: `ntake-${props.stage}-ws`,
      connectRouteOptions: {
        integration: new WebSocketLambdaIntegration("WsConnectInt", wsConnectFn),
        authorizer: wsAuthorizer,
      },
      disconnectRouteOptions: {
        integration: new WebSocketLambdaIntegration("WsDisconnectInt", wsDisconnectFn),
      },
    });

    const wsStage = new apigwv2.WebSocketStage(this, "WsStage", {
      webSocketApi: wsApi,
      stageName: props.stage,
      autoDeploy: true,
    });

    // writes — confirm (execute an action) + the two direct REST writes (create a
    // work item, append a human update). One Lambda because all three need the
    // same role (design B groups by role): read+write on the table + GSIs, and
    // execute-api:ManageConnections on the WS API to post the live-sync nudge.
    // Created AFTER the WS API so its env can carry the management endpoint
    // (https://{apiId}.execute-api.{region}/{stage}) the poster calls.
    const wsManagementEndpoint = `https://${wsApi.apiId}.execute-api.${region}.amazonaws.com/${wsStage.stageName}`;
    const writesFn = makeFn("WritesFn", "handlers.http_api.writes_handler", {
      environment: { NTAKE_WS_ENDPOINT: wsManagementEndpoint },
    });
    this.table.grantReadWriteData(writesFn); // read + write on table + GSIs
    wsApi.grantManageConnections(writesFn); // execute-api:ManageConnections on the WS API ARN

    // --- HTTP API (AWS_LLD §4) -----------------------------------------------
    // Simple-response Lambda authorizer (payload format 2.0): SIMPLE response
    // type selects format 2.0 + `{isAuthorized, context}` — the shape the
    // handlers read. Identity source is the Authorization header. Applied as the
    // API default authorizer; the two public routes (/health, /pair) opt out
    // with NoneAuthorizer.
    const httpAuthorizer = new HttpLambdaAuthorizer("HttpAuthorizer", authorizerFn, {
      responseTypes: [HttpLambdaResponseType.SIMPLE], // => payload format 2.0 + simple responses
      identitySource: ["$request.header.Authorization"],
    });

    // createDefaultStage: false so we can create the $default stage explicitly
    // and attach the per-stage throttle (apiThrottle) to its default route
    // settings.
    const httpApi = new apigwv2.HttpApi(this, "HttpApi", {
      apiName: `ntake-${props.stage}-http`,
      defaultAuthorizer: httpAuthorizer,
      createDefaultStage: false,
    });

    const httpStage = new apigwv2.HttpStage(this, "HttpDefaultStage", {
      httpApi,
      stageName: "$default",
      autoDeploy: true,
      throttle: {
        rateLimit: props.apiThrottle.rateLimit,
        burstLimit: props.apiThrottle.burstLimit,
      },
    });

    const readsInt = new HttpLambdaIntegration("ReadsInt", readsFn);

    // GET /health — PUBLIC (no auth): the liveness probe.
    httpApi.addRoutes({
      path: "/health",
      methods: [apigwv2.HttpMethod.GET],
      integration: readsInt,
      authorizer: new apigwv2.HttpNoneAuthorizer(),
    });

    // Authorized GET reads → reads Lambda (uses the API default authorizer).
    for (const p of ["/events", "/board", "/work-items", "/work-items/{id}", "/members"]) {
      httpApi.addRoutes({
        path: p,
        methods: [apigwv2.HttpMethod.GET],
        integration: readsInt,
      });
    }

    // Authorized POSTs.
    httpApi.addRoutes({
      path: "/capture",
      methods: [apigwv2.HttpMethod.POST],
      integration: new HttpLambdaIntegration("CaptureInt", captureFn),
    });
    // The write routes share one integration (the writes Lambda dispatches on the
    // route key). GET /work-items stays on the reads Lambda — same path, different
    // method → a separate API GW route.
    const writesInt = new HttpLambdaIntegration("WritesInt", writesFn);
    for (const p of ["/actions/confirm", "/work-items", "/work-items/{id}/updates"]) {
      httpApi.addRoutes({
        path: p,
        methods: [apigwv2.HttpMethod.POST],
        integration: writesInt,
      });
    }
    httpApi.addRoutes({
      path: "/pairing-codes",
      methods: [apigwv2.HttpMethod.POST],
      integration: new HttpLambdaIntegration("PairingInt", pairingFn),
    });

    // POST /pair — PUBLIC (no auth): the device enrolls here with a code.
    httpApi.addRoutes({
      path: "/pair",
      methods: [apigwv2.HttpMethod.POST],
      integration: new HttpLambdaIntegration("PairInt", pairFn),
      authorizer: new apigwv2.HttpNoneAuthorizer(),
    });

    // --- Outputs -------------------------------------------------------------
    new CfnOutput(this, "HttpApiUrl", { value: httpStage.url });
    new CfnOutput(this, "WsApiUrl", { value: wsStage.url });
  }
}
