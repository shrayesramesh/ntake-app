"""Tracer authorizer tests (Session 1.5) — the simple-response allow/deny decision.

Exercises :func:`tracer.authorizer.authorize` over the **real** lifted
:func:`core.tokens.hash_token` (AWS_LLD §5.1) with an in-memory ``lookup`` double,
so the device-token → member path is proven under ``make check`` with no AWS.

The tracer authorizer uses the HTTP API **simple response** format (payload
format 2.0): ``{"isAuthorized": bool, "context": {...}}`` rather than an IAM
policy document — the simpler, less error-prone contract. It gates only the HTTP
API; the tracer WebSocket ``$connect`` is unauthenticated (WS auth is Session-6).
The deployed Lambda shell (``handler``) is not tested here; the event-shape
parsing (``_extract_token``) and the pure decision (``authorize``) are.
"""

from __future__ import annotations

from typing import Any

from core.tokens import hash_token
from tracer.authorizer import _extract_token, authorize

SECRET = "tracer-test-secret"


def _store(*records: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a hash → record map keyed by each record's plaintext ``token``."""
    return {hash_token(r["token"], secret=SECRET): r for r in records}


def _lookup_from(store: dict[str, dict[str, Any]]):
    return lambda token_hash: store.get(token_hash)


def test_valid_token_allows_and_passes_member_context() -> None:
    store = _store(
        {"token": "good-token", "member_id": "MEM#alex", "family_id": "FAM#1"}
    )
    result = authorize("good-token", secret=SECRET, lookup=_lookup_from(store))
    assert result == {
        "isAuthorized": True,
        "context": {"member_id": "MEM#alex", "family_id": "FAM#1"},
    }


def test_unknown_token_denies() -> None:
    result = authorize("never-minted", secret=SECRET, lookup=lambda _h: None)
    assert result == {"isAuthorized": False}


def test_revoked_token_denies() -> None:
    store = _store(
        {
            "token": "revoked-token",
            "member_id": "MEM#sam",
            "family_id": "FAM#1",
            "revoked_at": "2026-01-01T00:00:00Z",
        }
    )
    result = authorize("revoked-token", secret=SECRET, lookup=_lookup_from(store))
    assert result == {"isAuthorized": False}


def test_missing_token_denies() -> None:
    result = authorize(None, secret=SECRET, lookup=lambda _h: None)
    assert result == {"isAuthorized": False}


def test_wrong_secret_does_not_authorize() -> None:
    # A token minted under one secret must not authorize under another.
    store = _store({"token": "t", "member_id": "MEM#alex", "family_id": "FAM#1"})
    result = authorize("t", secret="a-different-secret", lookup=_lookup_from(store))
    assert result == {"isAuthorized": False}


def test_extract_token_from_identity_source_v2() -> None:
    # HTTP API payload format 2.0 passes the resolved identity source(s) here.
    event = {"identitySource": ["Bearer abc123"]}
    assert _extract_token(event) == "abc123"


def test_extract_token_from_bearer_header() -> None:
    event = {"headers": {"Authorization": "Bearer abc123"}}
    assert _extract_token(event) == "abc123"


def test_extract_token_bare_value_without_bearer_prefix() -> None:
    event = {"identitySource": ["rawtokenvalue"]}
    assert _extract_token(event) == "rawtokenvalue"


def test_extract_token_absent_is_none() -> None:
    assert _extract_token({}) is None
