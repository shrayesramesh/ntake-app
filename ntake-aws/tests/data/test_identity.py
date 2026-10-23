"""Identity logic — token resolution, minting, and the pairing exchange (§5).

Tier-1 unit tests for the auth decision layer (``core/identity.py``) over the
in-memory ``TokenStore``. These pin the rules the authorizer and the pairing
endpoints depend on: a presented token resolves to a principal only when it
exists and is unrevoked; a minted token stores only its hash; a pairing code is
single-use, short-TTL, and attempt-capped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.identity import (
    PAIRING_MAX_ATTEMPTS,
    PairingError,
    Principal,
    create_pairing_code,
    mint_device_token,
    redeem_pairing_code,
    resolve_token,
)
from core.token_store_memory import InMemoryTokenStore
from core.tokens import hash_token

SECRET = "install-secret"
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _store() -> InMemoryTokenStore:
    return InMemoryTokenStore()


# --- resolve_token (the authorizer decision) -------------------------------


def test_resolve_token_returns_principal_for_a_minted_token() -> None:
    store = _store()
    minted = mint_device_token(
        store,
        family_id="fam1",
        member_id="m1",
        role="adult",
        label="phone",
        secret=SECRET,
        now=NOW,
    )

    principal = resolve_token(store, minted.plaintext, secret=SECRET)

    assert principal == Principal(member_id="m1", family_id="fam1", role="adult")


def test_resolve_token_none_for_missing_or_empty() -> None:
    store = _store()
    assert resolve_token(store, None, secret=SECRET) is None
    assert resolve_token(store, "", secret=SECRET) is None
    assert resolve_token(store, "never-minted", secret=SECRET) is None


def test_resolve_token_none_for_revoked() -> None:
    store = _store()
    minted = mint_device_token(
        store,
        family_id="fam1",
        member_id="m1",
        role="adult",
        label="phone",
        secret=SECRET,
        now=NOW,
    )
    store.revoke_device_token(minted.record.token_hash)

    assert resolve_token(store, minted.plaintext, secret=SECRET) is None


def test_resolve_token_none_under_a_different_secret() -> None:
    store = _store()
    minted = mint_device_token(
        store,
        family_id="fam1",
        member_id="m1",
        role="adult",
        label="phone",
        secret=SECRET,
        now=NOW,
    )
    # A token minted under one secret must not resolve under another.
    assert resolve_token(store, minted.plaintext, secret="other") is None


# --- mint_device_token -----------------------------------------------------


def test_mint_stores_only_the_hash_not_the_plaintext() -> None:
    store = _store()
    minted = mint_device_token(
        store,
        family_id="fam1",
        member_id="m1",
        role="adult",
        label="phone",
        secret=SECRET,
        now=NOW,
    )
    # The stored record carries the HASH, never the plaintext.
    assert minted.record.token_hash == hash_token(minted.plaintext, secret=SECRET)
    assert minted.record.token_hash != minted.plaintext
    stored = store.get_device_token(minted.record.token_hash)
    assert stored is not None and stored.member_id == "m1"


def test_mint_produces_distinct_tokens() -> None:
    store = _store()
    a = mint_device_token(
        store, family_id="f", member_id="m", role="adult", label="", secret=SECRET
    )
    b = mint_device_token(
        store, family_id="f", member_id="m", role="adult", label="", secret=SECRET
    )
    assert a.plaintext != b.plaintext
    assert a.record.token_hash != b.record.token_hash


# --- pairing code: create --------------------------------------------------


def test_create_pairing_code_is_six_digit_and_live() -> None:
    store = _store()
    pc = create_pairing_code(
        store, family_id="fam1", member_id="m1", role="adult", now=NOW
    )
    assert pc.code.isdigit() and len(pc.code) == 6
    assert pc.expires_at > NOW
    assert pc.consumed_at is None and pc.attempts == 0
    assert store.get_pairing_code(pc.code) is not None


# --- pairing code: redeem (the exchange) -----------------------------------


def test_redeem_valid_code_mints_a_device_token() -> None:
    store = _store()
    pc = create_pairing_code(
        store,
        family_id="fam1",
        member_id="m1",
        role="child",
        label="kid tablet",
        now=NOW,
    )

    minted = redeem_pairing_code(store, pc.code, secret=SECRET, now=NOW)

    # The new device gets a working token resolving to the granted principal.
    principal = resolve_token(store, minted.plaintext, secret=SECRET)
    assert principal == Principal(member_id="m1", family_id="fam1", role="child")
    # The code is now consumed.
    consumed = store.get_pairing_code(pc.code)
    assert consumed is not None and consumed.consumed_at is not None


def test_redeem_is_single_use() -> None:
    store = _store()
    pc = create_pairing_code(
        store, family_id="fam1", member_id="m1", role="adult", now=NOW
    )
    redeem_pairing_code(store, pc.code, secret=SECRET, now=NOW)

    with pytest.raises(PairingError):
        redeem_pairing_code(store, pc.code, secret=SECRET, now=NOW)


def test_redeem_unknown_code_raises() -> None:
    store = _store()
    with pytest.raises(PairingError):
        redeem_pairing_code(store, "000000", secret=SECRET, now=NOW)


def test_redeem_expired_code_raises() -> None:
    store = _store()
    pc = create_pairing_code(
        store, family_id="fam1", member_id="m1", role="adult", now=NOW
    )
    later = pc.expires_at + timedelta(seconds=1)
    with pytest.raises(PairingError):
        redeem_pairing_code(store, pc.code, secret=SECRET, now=later)


def test_redeem_is_attempt_capped() -> None:
    store = _store()
    pc = create_pairing_code(
        store, family_id="fam1", member_id="m1", role="adult", now=NOW
    )
    # Burn the cap with wrong (well, same but we simulate failures via a bad code
    # path): here we exhaust attempts on the real code by calling with an expired
    # clock so each raises but records an attempt.
    past_expiry = pc.expires_at + timedelta(seconds=1)
    for _ in range(PAIRING_MAX_ATTEMPTS):
        with pytest.raises(PairingError):
            redeem_pairing_code(store, pc.code, secret=SECRET, now=past_expiry)
    # Even a now-valid clock is refused once the attempt cap is hit.
    with pytest.raises(PairingError):
        redeem_pairing_code(store, pc.code, secret=SECRET, now=NOW)
