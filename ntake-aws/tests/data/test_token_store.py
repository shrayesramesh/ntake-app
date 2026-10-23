"""In-memory ``TokenStore`` edges + the pure identity-key composers (§5).

Covers the branches the happy-path identity tests don't reach: the key composers
(``token_pk``/``pairing_pk`` — the single source of identity-key knowledge, reused
by the Dynamo impl), and the in-memory store's no-op-on-miss/idempotent branches
(revoke/consume/record-attempt on a missing or already-settled record).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.schemas import DeviceToken, PairingCode
from core.token_store import pairing_pk, token_pk
from core.token_store_memory import InMemoryTokenStore

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def test_key_composers() -> None:
    assert token_pk("abc123") == "TOK#abc123"
    assert pairing_pk("000042") == "PAIR#000042"


def test_list_device_tokens_for_member() -> None:
    store = InMemoryTokenStore()
    store.put_device_token(
        DeviceToken(token_hash="h1", family_id="f", member_id="m1", created_at=NOW)
    )
    store.put_device_token(
        DeviceToken(token_hash="h2", family_id="f", member_id="m1", created_at=NOW)
    )
    store.put_device_token(
        DeviceToken(token_hash="h3", family_id="f", member_id="m2", created_at=NOW)
    )
    hashes = {t.token_hash for t in store.list_device_tokens_for_member("m1")}
    assert hashes == {"h1", "h2"}


def test_revoke_and_consume_on_missing_are_noops() -> None:
    store = InMemoryTokenStore()
    # No record present — must not raise.
    store.revoke_device_token("missing")
    store.consume_pairing_code("missing")
    store.record_pairing_attempt("missing")
    assert store.get_device_token("missing") is None
    assert store.get_pairing_code("missing") is None


def test_revoke_is_idempotent() -> None:
    store = InMemoryTokenStore()
    store.put_device_token(
        DeviceToken(token_hash="h1", family_id="f", member_id="m1", created_at=NOW)
    )
    store.revoke_device_token("h1")
    first = store.get_device_token("h1")
    assert first is not None and first.revoked_at is not None
    store.revoke_device_token("h1")  # second revoke keeps the original timestamp
    second = store.get_device_token("h1")
    assert second is not None and second.revoked_at == first.revoked_at


def test_consume_is_idempotent_and_record_attempt_increments() -> None:
    store = InMemoryTokenStore()
    pc = PairingCode(
        code="000001",
        family_id="f",
        member_id="m1",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    store.put_pairing_code(pc)
    store.record_pairing_attempt("000001")
    store.record_pairing_attempt("000001")
    after = store.get_pairing_code("000001")
    assert after is not None and after.attempts == 2

    store.consume_pairing_code("000001")
    first = store.get_pairing_code("000001")
    assert first is not None and first.consumed_at is not None
    store.consume_pairing_code("000001")  # idempotent
    second = store.get_pairing_code("000001")
    assert second is not None and second.consumed_at == first.consumed_at
