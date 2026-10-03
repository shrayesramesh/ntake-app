import { Stack, StackProps, RemovalPolicy, Duration, CfnOutput } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as path from "node:path";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import {
  HttpLambdaAuthorizer,
  HttpLambdaResponseType,
} from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import { WebSocketLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as iam from "aws-cdk-lib/aws-iam";

/**
 * ⚠️ THROWAWAY TRACER-BULLET STACK (AWS_PLAN Part II, Session 1.5). ⚠️
 *
 * A deliberately-minimal walking skeleton that de-risks the three cloud-only
 * assumptions local tests cannot prove — IAM, real Bedrock tool-use, and the
 * API-GW → authorizer → WebSocket post-back loop — BEFORE Sessions 2-7 build on
 * them. It is a **separate stack** from the real (empty) `NtakeStack` on purpose:
 * when Session 5 builds the real architecture into `NtakeStack`, this whole stack
 * and the `tracer/` Python package are deleted in one move, with zero risk of
 * unpicking throwaway resources out of the real stack. Deployed as
 * `TracerStack-dev` only — there is no prod tracer.
 *
 * Resources: one trivial DynamoDB table, a Secrets Manager secret (the HMAC token
 * secret), four Python Lambdas (app handler, device-token authorizer, WS connect,
 * WS disconnect) + one Bedrock-tracer Lambda, an HTTP API (authorized) and a
 * WebSocket API ($connect/$disconnect with the authorizer + a hard-coded
 * post-back). IAM is scoped per-Lambda — that scoping is itself part of what the
 * tracer validates.
 */
export interface TracerStackProps extends StackProps {
  /** Small, cheap model — the cost dial (AWS_HLD §7a). Haiku/Nova. */
  readonly bedrockModelId: string;
}

export class TracerStack extends Stack {
  constructor(scope: Construct, id: string, props: TracerStackProps) {
    super(scope, id, props);

    // The Python Lambda asset: the package root, with everything that is not the
    // tracer handlers or the (stdlib-only) lifted core excluded, so .venv, infra,
    // tests, specs and caches never ship in the function bundle. `core.tokens`
    // (the one real seam the authorizer uses) imports only the stdlib, so no
    // pip install / bundling step is needed for this throwaway slice.
    const code = lambda.Code.fromAsset(path.join(__dirname, "..", ".."), {
      exclude: [
        ".venv",
        ".git",
        "infra",
        "tests",
        "spec",
        "scripts",
        "handlers",
        "adapters",
        "*.md",
        "*.toml",
        "*.txt",
        "*.cfg",
        ".coverage",
        "**/__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
      ],
    });

    // --- DynamoDB: one trivial table (pk/sk), disposable ---------------------
    const table = new dynamodb.Table(this, "TracerTable", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.DESTROY, // throwaway
    });

    // --- Secrets Manager: the HMAC token secret ------------------------------
    // Auto-generates a random secret string; the authorizer reads it to hash the
    // presented device token (AWS_LLD §5.1). A matching plaintext token's hash is
    // seeded into the table out-of-band during validation (Session 1.5 step 4).
    const tokenSecret = new secretsmanager.Secret(this, "TokenSecret", {
      description: "⚠️ tracer-bullet HMAC device-token secret (throwaway)",
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const commonEnv = {
      TRACER_TABLE_NAME: table.tableName,
      NTAKE_TOKEN_SECRET: tokenSecret.secretValue.unsafeUnwrap(),
    };

    const runtime = lambda.Runtime.PYTHON_3_12;

    // --- Lambdas (each gets a tightly-scoped role) ---------------------------

    // Authorizer: reads the secret to hash the token + GetItem on the table only.
    const authorizerFn = new lambda.Function(this, "AuthorizerFn", {
      runtime,
      code,
      handler: "tracer.authorizer.handler",
      timeout: Duration.seconds(10),
      environment: commonEnv,
    });
    table.grantReadData(authorizerFn); // GetItem only — scoped read.

    // App handler: proves IAM via a DynamoDB put+get round trip, nothing else.
    const appFn = new lambda.Function(this, "AppFn", {
      runtime,
      code,
      handler: "tracer.app_handler.handler",
      timeout: Duration.seconds(10),
      environment: commonEnv,
    });
    table.grantReadWriteData(appFn); // scoped to this table only.

    // Bedrock tracer: one real Converse tool-use call. bedrock:InvokeModel only.
    const bedrockFn = new lambda.Function(this, "BedrockFn", {
      runtime,
      code,
      handler: "tracer.bedrock_tracer.handler",
      timeout: Duration.seconds(30), // the capture path's two-call budget (AWS_LLD §7.1)
      environment: {
        TRACER_BEDROCK_MODEL_ID: props.bedrockModelId,
      },
    });
    // The model id is an INFERENCE PROFILE id (e.g. "us.anthropic.claude-haiku-...").
    // Invoking a profile needs bedrock:InvokeModel on BOTH the profile ARN AND the
    // underlying foundation-model ARNs in every region the profile routes to
    // (the "us." profiles fan to us-east-1/us-east-2/us-west-2). Still scoped to
    // this one model family — never bedrock:* on *.
    const profileId = props.bedrockModelId; // us.anthropic.claude-...
    const foundationModelId = profileId.replace(/^us\./, ""); // anthropic.claude-...
    const profileRegions = ["us-east-1", "us-east-2", "us-west-2"];
    bedrockFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: [
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/${profileId}`,
          ...profileRegions.map(
            (r) => `arn:aws:bedrock:${r}::foundation-model/${foundationModelId}`,
          ),
        ],
      }),
    );

    // WS connect/disconnect: write/delete connection items + post back on connect.
    const wsConnectFn = new lambda.Function(this, "WsConnectFn", {
      runtime,
      code,
      handler: "tracer.ws_handler.connect",
      timeout: Duration.seconds(10),
      environment: commonEnv,
    });
    table.grantReadWriteData(wsConnectFn);

    const wsDisconnectFn = new lambda.Function(this, "WsDisconnectFn", {
      runtime,
      code,
      handler: "tracer.ws_handler.disconnect",
      timeout: Duration.seconds(10),
      environment: commonEnv,
    });
    table.grantReadWriteData(wsDisconnectFn);

    // --- HTTP API: authorized app + bedrock routes ---------------------------
    const httpAuthorizer = new HttpLambdaAuthorizer(
      "TracerHttpAuthorizer",
      authorizerFn,
      {
        // SIMPLE response => the Lambda returns {isAuthorized, context} and API GW
        // uses payload format 2.0. Simpler + less footgun-prone than an IAM policy.
        responseTypes: [HttpLambdaResponseType.SIMPLE],
        identitySource: ["$request.header.Authorization"],
        resultsCacheTtl: Duration.seconds(0), // no caching — easier to validate
      },
    );

    const httpApi = new apigwv2.HttpApi(this, "TracerHttpApi", {
      defaultAuthorizer: httpAuthorizer,
    });
    httpApi.addRoutes({
      // NOT "/ping" — that literal path is a near-universal health-probe route and
      // gets intercepted/answered by edge/network appliances before reaching the
      // integration (observed in Session 1.5). Use an app-specific path.
      path: "/tracer-iam",
      methods: [apigwv2.HttpMethod.GET],
      integration: new HttpLambdaIntegration("AppIntegration", appFn),
    });
    httpApi.addRoutes({
      path: "/tracer-bedrock",
      methods: [apigwv2.HttpMethod.POST],
      integration: new HttpLambdaIntegration("BedrockIntegration", bedrockFn),
    });

    // --- WebSocket API: $connect (UNAUTHENTICATED in the tracer) / $disconnect
    // The tracer's WS job is only to prove the post-back loop (connect → server
    // postToConnection → client receives). Gating $connect with a custom authorizer
    // is a Session-6 concern — and WS authorizers have no simple-response mode, so
    // leaving it out keeps the tracer simple. $connect still writes the connection
    // and posts back the hard-coded nudge.
    const wsApi = new apigwv2.WebSocketApi(this, "TracerWsApi", {
      connectRouteOptions: {
        integration: new WebSocketLambdaIntegration("WsConnectIntegration", wsConnectFn),
      },
      disconnectRouteOptions: {
        integration: new WebSocketLambdaIntegration(
          "WsDisconnectIntegration",
          wsDisconnectFn,
        ),
      },
    });
    const wsStage = new apigwv2.WebSocketStage(this, "TracerWsStage", {
      webSocketApi: wsApi,
      stageName: "dev",
      autoDeploy: true,
    });
    // The connect handler posts back via the Management API — grant it.
    wsApi.grantManageConnections(wsConnectFn);

    // --- Outputs: the agent reads these to run the Session-1.5 validations ---
    new CfnOutput(this, "HttpApiUrl", { value: httpApi.apiEndpoint });
    new CfnOutput(this, "WebSocketUrl", { value: wsStage.url });
    new CfnOutput(this, "TableName", { value: table.tableName });
    new CfnOutput(this, "TokenSecretArn", { value: tokenSecret.secretArn });
    new CfnOutput(this, "BedrockModelId", { value: props.bedrockModelId });
  }
}
