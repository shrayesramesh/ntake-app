"""Tracer HTTP + WebSocket shape tests (Session 1.5).

Covers the pure response/nudge shapers of the throwaway handlers — the parts that
run under ``make check``. The DynamoDB round trip (``app_handler.handler``) and
the ``postToConnection`` post-back (``ws_handler.connect``) are deployed-only
(IAM / Management API) and are validated against the deployed slice, not here.
"""

from __future__ import annotations

import json

from tracer.app_handler import _authorizer_context, error, ok
from tracer.ws_handler import HARDCODED_NUDGE, nudge


def test_ok_is_200_json() -> None:
    resp = ok({"hello": "world"})
    assert resp["statusCode"] == 200
    assert resp["headers"]["content-type"] == "application/json"
    assert json.loads(resp["body"]) == {"hello": "world"}


def test_error_carries_status_and_message() -> None:
    resp = error(500, "AccessDeniedException: nope")
    assert resp["statusCode"] == 500
    assert json.loads(resp["body"]) == {"error": "AccessDeniedException: nope"}


def test_authorizer_context_reads_http_api_v2_shape() -> None:
    event = {
        "requestContext": {
            "authorizer": {"lambda": {"member_id": "MEM#alex", "family_id": "FAM#1"}}
        }
    }
    assert _authorizer_context(event) == {
        "member_id": "MEM#alex",
        "family_id": "FAM#1",
    }


def test_authorizer_context_absent_is_empty() -> None:
    assert _authorizer_context({}) == {}


def test_nudge_is_entity_id_op_shape() -> None:
    payload = json.loads(nudge())
    assert set(payload) == {"entity", "id", "op"}
    assert payload == HARDCODED_NUDGE
