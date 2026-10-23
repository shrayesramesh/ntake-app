"""Session 6 infra assertions — synth the stack, assert the request path.

``make test-infra`` runs ``.venv/bin/pytest tests/infra``. This module replaces
the Session-1 placeholder. It synthesizes ``NtakeStack-dev`` once (a
session-scoped fixture: ``npm run build`` then ``npx cdk synth``) and loads the
CloudFormation template, then asserts the Session-6 shape (AWS_LLD §4/§5/§7):

* the HMAC token secret exists alongside the Anthropic secret;
* every handler Lambda is python3.12 and the capture Lambda alone has the 30s
  timeout + the Anthropic model env + no ``bedrock:`` action anywhere;
* the HTTP API's only public (authorizer-less) routes are ``GET /health`` and
  ``POST /pair``; the authorizer is a simple-response payload-2.0 Lambda
  authorizer; the WS API has ``$connect`` (authorized) + ``$disconnect``;
* IAM is construct-scoped per design B — the reads role carries no write
  actions, and the confirm role carries ``execute-api:ManageConnections``.

Assertions scan the ``Resources`` dict by ``Type`` + properties so they survive
CloudFormation logical-id suffixes (never hard-code a logical id). Stdlib +
pytest only (json, subprocess, pathlib).

NOTE on the Lambda count: the Python handler surface is exactly EIGHT entry
points — ``authorizer.handler``; ``http_api``'s reads/capture/confirm/pairing/
pair; and ``ws``'s connect/disconnect — so design B (one Lambda per handler)
yields eight functions. The Session-6 brief's "9 total" is an arithmetic slip
(it also says "Seven Lambda functions" in the same paragraph); there is no ninth
handler in the code to wire. These tests assert the real count, 8.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

# infra/ lives beside this package root: tests/infra/ -> ntake-aws/ -> infra/.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_INFRA_DIR = _PACKAGE_ROOT / "infra"
_TEMPLATE = _INFRA_DIR / "cdk.out" / "NtakeStack-dev.template.json"

_READ_ONLY_DDB = {
    "dynamodb:GetItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:BatchGetItem",
}
_WRITE_DDB = {
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem",
}


@pytest.fixture(scope="session")
def template() -> dict:
    """Synthesize NtakeStack-dev once and return its CloudFormation template.

    Builds (tsc) then synths via subprocess. If a freshly-built synth has
    already produced the template this session we still re-synth to stay honest
    about the current source; the cost is a few seconds, amortized across the
    module by ``scope="session"``.
    """
    subprocess.run(
        ["npm", "run", "build"],
        cwd=_INFRA_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["npx", "cdk", "synth", "NtakeStack-dev"],
        cwd=_INFRA_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    assert _TEMPLATE.exists(), f"synth did not produce {_TEMPLATE}"
    return json.loads(_TEMPLATE.read_text())


# --- small helpers over the template --------------------------------------


def _by_type(template: dict, cfn_type: str) -> dict[str, dict]:
    """Logical-id -> resource dict for every resource of ``cfn_type``."""
    return {
        lid: res
        for lid, res in template["Resources"].items()
        if res["Type"] == cfn_type
    }


def _functions(template: dict) -> dict[str, dict]:
    return _by_type(template, "AWS::Lambda::Function")


def _fn_by_handler(template: dict, handler: str) -> dict:
    """The single Lambda whose Handler matches ``handler`` (asserts uniqueness)."""
    hits = [
        res
        for res in _functions(template).values()
        if res["Properties"].get("Handler") == handler
    ]
    assert len(hits) == 1, f"expected exactly one {handler!r}, found {len(hits)}"
    return hits[0]


def _statement_actions(statement: dict) -> set[str]:
    action = statement.get("Action", [])
    actions = action if isinstance(action, list) else [action]
    return {a for a in actions if isinstance(a, str)}


def _policy_actions_for_role(template: dict, role_logical_id: str) -> set[str]:
    """Union of all Action strings across policies attached to a given role."""
    actions: set[str] = set()
    for policy in _by_type(template, "AWS::IAM::Policy").values():
        role_refs = {
            r.get("Ref")
            for r in policy["Properties"].get("Roles", [])
            if isinstance(r, dict)
        }
        if role_logical_id in role_refs:
            for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
                actions |= _statement_actions(stmt)
    return actions


def _role_id_of(fn: dict) -> str:
    """The logical id of a function's execution role (from its Role GetAtt)."""
    role = fn["Properties"]["Role"]
    # CDK emits Role as { "Fn::GetAtt": ["<RoleLogicalId>", "Arn"] }.
    return role["Fn::GetAtt"][0]


def _env_of(fn: dict) -> dict:
    return fn["Properties"].get("Environment", {}).get("Variables", {})


# --- secrets ---------------------------------------------------------------


def test_token_secret_exists_alongside_anthropic(template: dict) -> None:
    names = {
        s["Properties"].get("Name")
        for s in _by_type(template, "AWS::SecretsManager::Secret").values()
    }
    assert "ntake-dev/token-secret" in names
    assert "ntake-dev/anthropic-api-key" in names


# --- Lambdas ---------------------------------------------------------------

_EXPECTED_HANDLERS = {
    "handlers.authorizer.handler",
    "handlers.http_api.reads_handler",
    "handlers.http_api.capture_handler",
    "handlers.http_api.confirm_handler",
    "handlers.http_api.pairing_handler",
    "handlers.http_api.pair_handler",
    "handlers.ws.connect_handler",
    "handlers.ws.disconnect_handler",
}


def test_eight_python312_lambdas(template: dict) -> None:
    fns = _functions(template)
    # One Lambda per Python handler entry point (design B). The brief's "9" is an
    # arithmetic slip; the code has exactly eight handlers (see module docstring).
    assert len(fns) == 8
    runtimes = {f["Properties"]["Runtime"] for f in fns.values()}
    assert runtimes == {"python3.12"}
    handlers = {f["Properties"]["Handler"] for f in fns.values()}
    assert handlers == _EXPECTED_HANDLERS


def test_capture_lambda_timeout_and_model_env(template: dict) -> None:
    capture = _fn_by_handler(template, "handlers.http_api.capture_handler")
    assert capture["Properties"]["Timeout"] == 30
    env = _env_of(capture)
    # The model id flows from props.anthropicModelId as a plain string env.
    assert env.get("NTAKE_ANTHROPIC_MODEL") == "claude-haiku-4-5"


def test_no_bedrock_action_anywhere(template: dict) -> None:
    # The Anthropic-over-HTTPS pivot (AWS_HLD §10) means no bedrock IAM at all.
    blob = json.dumps(template).lower()
    assert "bedrock:" not in blob


# --- HTTP API authorizer + routes ------------------------------------------


def _http_routes(template: dict) -> dict[str, dict]:
    """RouteKey -> route props for HTTP routes (those with a 'GET '/'POST ' key).

    WebSocket routes use ``$connect``/``$disconnect`` keys; HTTP routes use
    ``<METHOD> <path>``. Both are ``AWS::ApiGatewayV2::Route``, so split on the
    route key shape.
    """
    out = {}
    for res in _by_type(template, "AWS::ApiGatewayV2::Route").values():
        key = res["Properties"]["RouteKey"]
        if key.startswith("$"):
            continue
        out[key] = res["Properties"]
    return out


def test_only_health_and_pair_are_public(template: dict) -> None:
    routes = _http_routes(template)
    public = {
        key
        for key, props in routes.items()
        if props.get("AuthorizationType", "NONE") == "NONE"
    }
    assert public == {"GET /health", "POST /pair"}
    # And every other HTTP route is CUSTOM (Lambda authorizer).
    authorized = set(routes) - public
    assert authorized  # sanity: there are authorized routes
    for key in authorized:
        assert routes[key]["AuthorizationType"] == "CUSTOM"
        assert "AuthorizerId" in routes[key]


def test_http_authorizer_is_simple_response_payload_2(template: dict) -> None:
    authorizers = _by_type(template, "AWS::ApiGatewayV2::Authorizer")
    http_auth = [
        a
        for a in authorizers.values()
        if a["Properties"].get("AuthorizerPayloadFormatVersion") == "2.0"
    ]
    assert len(http_auth) == 1
    props = http_auth[0]["Properties"]
    assert props["AuthorizerType"] == "REQUEST"
    assert props["EnableSimpleResponses"] is True
    assert props["IdentitySource"] == ["$request.header.Authorization"]


# --- WebSocket API ---------------------------------------------------------


def test_websocket_has_connect_and_disconnect(template: dict) -> None:
    ws_keys = {
        res["Properties"]["RouteKey"]
        for res in _by_type(template, "AWS::ApiGatewayV2::Route").values()
        if res["Properties"]["RouteKey"].startswith("$")
    }
    assert "$connect" in ws_keys
    assert "$disconnect" in ws_keys
    # $connect is authorized (same authorizer, ?token=); $disconnect is not.
    routes = _by_type(template, "AWS::ApiGatewayV2::Route")
    connect = next(
        r for r in routes.values() if r["Properties"]["RouteKey"] == "$connect"
    )
    assert connect["Properties"]["AuthorizationType"] == "CUSTOM"


def test_ws_authorizer_uses_querystring_token(template: dict) -> None:
    authorizers = _by_type(template, "AWS::ApiGatewayV2::Authorizer")
    ws_auth = [
        a
        for a in authorizers.values()
        if a["Properties"].get("IdentitySource") == ["route.request.querystring.token"]
    ]
    assert len(ws_auth) == 1
    assert ws_auth[0]["Properties"]["AuthorizerType"] == "REQUEST"


# --- IAM scoping (design B) ------------------------------------------------


def test_reads_role_has_no_write_actions(template: dict) -> None:
    reads = _fn_by_handler(template, "handlers.http_api.reads_handler")
    actions = _policy_actions_for_role(template, _role_id_of(reads))
    # It must have read actions...
    assert actions & _READ_ONLY_DDB
    # ...and NONE of the mutating ones.
    writes = actions & _WRITE_DDB
    assert not writes, f"reads role has write actions: {writes}"


def test_confirm_role_can_manage_ws_connections(template: dict) -> None:
    confirm = _fn_by_handler(template, "handlers.http_api.confirm_handler")
    actions = _policy_actions_for_role(template, _role_id_of(confirm))
    assert "execute-api:ManageConnections" in actions
    # Confirm also writes (it executes actions then publishes).
    assert actions & _WRITE_DDB


def test_capture_role_reads_secret_but_not_bedrock(template: dict) -> None:
    capture = _fn_by_handler(template, "handlers.http_api.capture_handler")
    actions = _policy_actions_for_role(template, _role_id_of(capture))
    assert "secretsmanager:GetSecretValue" in actions
    assert not {a for a in actions if a.startswith("bedrock:")}
    # Capture only reads the table (no writes on the propose-only path).
    assert not (actions & _WRITE_DDB)
