"""HTTP API Lambda shells — parse the event, delegate to the tested logic.

One module per the design-B grouping would be ideal, but the routes share event
parsing + response formatting, so they live together here and CDK wires each
route to the matching entry function (``reads_handler`` / ``capture_handler`` /
``confirm_handler`` / ``pairing_handler``) with its own role + timeout. Each
entry is thin: read the authorizer context + body from the API GW v2 event,
build the real adapters (``_runtime``), call the pure handler logic
(``_support`` / ``_auth``), and return an API GW v2 response.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from core.engine.engine import ActionError
from core.identity import Principal
from core.schemas import ConfirmAction
from handlers import _runtime
from handlers._auth import PairingError, create_pairing, redeem_pairing
from handlers._support import (
    event_read,
    family_timezone,
    member_for,
    run_capture,
    run_confirm,
    work_item_read,
)


def _response(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _principal(event: dict[str, Any]) -> Principal:
    """The resolved principal from the authorizer context on the event."""
    ctx = event.get("requestContext", {}).get("authorizer", {}).get("lambda", {})
    return Principal(
        member_id=ctx["member_id"], family_id=ctx["family_id"], role=ctx["role"]
    )


def _body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _require_member(event: dict[str, Any], repo: Any):
    """Resolve the principal to a Member, or raise a 404-ish lookup miss."""
    principal = _principal(event)
    member = member_for(repo, principal)
    return principal, member


# --- reads -----------------------------------------------------------------


def reads_handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """GET routes: health, events, board, work-items, a single work item, members."""
    route = event.get("rawPath", "") or event.get("routeKey", "")
    if route.endswith("/health") or route == "GET /health":
        return _response(200, {"status": "ok"})

    repo = _runtime.repository()
    principal = _principal(event)
    family_id = principal.family_id
    tz = family_timezone(repo, family_id)

    if route.endswith("/events"):
        events = repo.list_events(family_id)
        return _response(
            200, [event_read(e, tz).model_dump(mode="json") for e in events]
        )
    if route.endswith("/board"):
        board = repo.list_board(family_id)
        return _response(
            200,
            {
                col: [work_item_read(wi, tz).model_dump(mode="json") for wi in items]
                for col, items in board.items()
            },
        )
    if "/work-items/" in route:
        work_item_id = route.rsplit("/", 1)[-1]
        wi = repo.get_work_item(family_id, work_item_id)
        if wi is None:
            return _response(404, {"error": "work item not found"})
        return _response(200, work_item_read(wi, tz).model_dump(mode="json"))
    if route.endswith("/work-items"):
        items = repo.list_work_items(family_id)
        return _response(
            200, [work_item_read(wi, tz).model_dump(mode="json") for wi in items]
        )
    if route.endswith("/members"):
        members = repo.list_members(family_id)
        return _response(200, [m.model_dump(mode="json") for m in members])
    return _response(404, {"error": "not found"})


# --- capture ---------------------------------------------------------------


def capture_handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """POST /capture — LINK→PROPOSE, propose-only (nothing written)."""
    repo = _runtime.repository()
    principal, member = _require_member(event, repo)
    if member is None:
        return _response(404, {"error": "member not found"})
    text = str(_body(event).get("text", ""))
    resp = run_capture(repo, _runtime.anthropic_client(), member, text)
    return _response(201, resp.model_dump(mode="json"))


# --- confirm ---------------------------------------------------------------


def confirm_handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """POST /actions/confirm — execute via the registry, write, publish once."""
    repo = _runtime.repository()
    _principal_, member = _require_member(event, repo)
    if member is None:
        return _response(404, {"error": "member not found"})
    action = ConfirmAction.model_validate(_body(event))
    try:
        result = run_confirm(
            repo,
            member,
            name=action.name,
            params=action.params,
            target_id=action.target_id,
            target_type=action.target_type,
            poster=_runtime.connection_poster(),
        )
    except ActionError as e:
        return _response(422, {"error": str(e)})
    return _response(200, result)


# --- pairing (create [authed] + redeem [public]) ---------------------------


def pairing_handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """POST /pairing-codes — an enrolled member mints a 6-digit code."""
    store = _runtime.token_store()
    principal = _principal(event)
    label = str(_body(event).get("label", ""))
    code = create_pairing(store, principal, label=label)
    return _response(
        201, {"code": code.code, "expires_at": code.expires_at.isoformat()}
    )


def pair_handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """POST /pair — public exchange: a 6-digit code → a device token."""
    store = _runtime.token_store()
    code = str(_body(event).get("code", ""))
    label = str(_body(event).get("label", ""))
    try:
        minted = redeem_pairing(
            store, code, secret=_runtime.token_secret(), label=label
        )
    except PairingError:
        return _response(400, {"error": "invalid pairing code"})
    return _response(200, {"token": minted.plaintext})


# Route dispatch table (CDK wires each route to the matching Lambda; this map is
# a convenience for a single-function deployment or local dispatch).
ROUTES: dict[str, Callable[[dict[str, Any], object], dict[str, Any]]] = {
    "capture": capture_handler,
    "confirm": confirm_handler,
    "pairing": pairing_handler,
    "pair": pair_handler,
    "reads": reads_handler,
}
