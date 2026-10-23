"""Authorizer + pairing handler logic (§5) — token extraction, allow/deny, exchange.

Tier-1 tests for ``handlers._auth`` over the in-memory ``TokenStore``: the
Bearer/``?token=`` extraction, the allow/deny decision + principal context, and
the create→redeem pairing exchange that onboards a new device.
"""

from __future__ import annotations

import pytest

from core.identity import Principal, mint_device_token
from core.token_store_memory import InMemoryTokenStore
from handlers._auth import (
    PairingError,
    authorize,
    create_pairing,
    extract_token,
    redeem_pairing,
)

SECRET = "install-secret"


# --- token extraction ------------------------------------------------------


def test_extract_bearer_header() -> None:
    assert extract_token(authorization_header="Bearer abc.def") == "abc.def"
    assert extract_token(authorization_header="bearer abc.def") == "abc.def"


def test_extract_bare_header_value() -> None:
    assert extract_token(authorization_header="rawtoken") == "rawtoken"


def test_extract_query_token_for_websocket() -> None:
    assert extract_token(query_token="wstoken") == "wstoken"


def test_extract_none_when_absent() -> None:
    assert extract_token() is None


# --- authorize decision ----------------------------------------------------


def test_authorize_allows_a_valid_token_with_principal() -> None:
    store = InMemoryTokenStore()
    minted = mint_device_token(
        store, family_id="fam1", member_id="m1", role="adult", label="", secret=SECRET
    )
    decision = authorize(store, minted.plaintext, secret=SECRET)
    assert decision.allowed is True
    assert decision.principal == Principal(
        member_id="m1", family_id="fam1", role="adult"
    )


def test_authorize_denies_unknown_token() -> None:
    store = InMemoryTokenStore()
    decision = authorize(store, "nope", secret=SECRET)
    assert decision.allowed is False and decision.principal is None


# --- pairing exchange ------------------------------------------------------


def test_create_then_redeem_onboards_a_new_device() -> None:
    store = InMemoryTokenStore()
    creator = Principal(member_id="m1", family_id="fam1", role="adult")

    code = create_pairing(store, creator, label="new tablet")
    assert code.code.isdigit() and len(code.code) == 6

    minted = redeem_pairing(store, code.code, secret=SECRET, label="new tablet")

    # The device's new token authorizes as the creator's principal.
    decision = authorize(store, minted.plaintext, secret=SECRET)
    assert decision.allowed is True
    assert decision.principal == creator


def test_redeem_bad_code_raises_pairing_error() -> None:
    store = InMemoryTokenStore()
    with pytest.raises(PairingError):
        redeem_pairing(store, "123456", secret=SECRET)
