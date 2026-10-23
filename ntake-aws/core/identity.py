"""Identity logic — resolve a token, mint a device, create/redeem a pairing code.

The pure decision layer the authorizer + pairing handlers sit on (AWS_LLD §5),
kept out of the Lambda/HTTP shells so the rules are unit-testable with no network.
It depends only on the :class:`core.token_store.TokenStore` seam and the
``core.tokens`` HMAC primitives.

Flows:

* **resolve_token** — the authorizer's decision: hash the presented plaintext,
  look up ``TOK#<hash>``, require it exists and is not revoked, return the
  resolved principal (or ``None`` → deny).
* **mint_device_token** — create a full-entropy token, store only its hash, and
  return the plaintext **once** (the caller shows it; it is never persisted).
  Used by the pairing exchange and by first-device bootstrap.
* **create_pairing_code / redeem_pairing_code** — the 6-digit enrollment
  exchange (AWS_LLD §5.4). ``create`` is called by an already-enrolled member;
  ``redeem`` is the public exchange that validates the code (exists, not
  consumed, not expired, under the attempt cap) and mints a device token for the
  new device.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.schemas import DeviceToken, PairingCode
from core.token_store import TokenStore
from core.tokens import generate_token, hash_token

# Pairing-code policy (cheap accident guards; private family app — see the repo
# threat-model note, not public-service hardening).
PAIRING_CODE_TTL = timedelta(minutes=10)
PAIRING_MAX_ATTEMPTS = 5
_PAIRING_CODE_DIGITS = 6


@dataclass(frozen=True)
class Principal:
    """The resolved identity the authorizer passes to the handlers."""

    member_id: str
    family_id: str
    role: str


@dataclass(frozen=True)
class MintedToken:
    """A freshly minted device token: the stored record + the once-shown plaintext."""

    plaintext: str
    record: DeviceToken


class PairingError(Exception):
    """A pairing code could not be redeemed (unknown / expired / consumed / capped).

    Deliberately carries a single opaque message to the caller; the handler maps
    it to a generic failure rather than leaking which condition failed.
    """


# --- authorizer decision ----------------------------------------------------


def resolve_token(
    store: TokenStore, plaintext: str | None, *, secret: str
) -> Principal | None:
    """Resolve a presented plaintext token to a principal, or ``None`` to deny.

    Hashes the token under the per-install secret, looks up the device-token
    record, and requires it to exist and be unrevoked. Any miss (no token, unknown
    hash, revoked) returns ``None`` — indistinguishable to the caller (the
    authorizer denies uniformly).
    """
    if not plaintext:
        return None
    token_hash = hash_token(plaintext, secret=secret)
    record = store.get_device_token(token_hash)
    if record is None or record.revoked_at is not None:
        return None
    return Principal(
        member_id=record.member_id,
        family_id=record.family_id,
        role=record.role,
    )


# --- minting a device token -------------------------------------------------


def mint_device_token(
    store: TokenStore,
    *,
    family_id: str,
    member_id: str,
    role: str,
    label: str,
    secret: str,
    now: datetime | None = None,
) -> MintedToken:
    """Mint a full-entropy device token; store only its hash; return plaintext once.

    The plaintext is returned to the caller to show exactly once (it is never
    persisted — only ``hash_token(plaintext)`` is stored). Used by the pairing
    exchange and first-device bootstrap.
    """
    created = now or datetime.now(UTC)
    plaintext = generate_token()
    record = DeviceToken(
        token_hash=hash_token(plaintext, secret=secret),
        family_id=family_id,
        member_id=member_id,
        role=role,
        label=label,
        created_at=created,
    )
    store.put_device_token(record)
    return MintedToken(plaintext=plaintext, record=record)


# --- pairing-code exchange (AWS_LLD §5.4) -----------------------------------


def _new_pairing_code() -> str:
    """A fresh 6-digit numeric pairing code (zero-padded)."""
    return f"{secrets.randbelow(10**_PAIRING_CODE_DIGITS):0{_PAIRING_CODE_DIGITS}d}"


def create_pairing_code(
    store: TokenStore,
    *,
    family_id: str,
    member_id: str,
    role: str,
    label: str = "",
    now: datetime | None = None,
) -> PairingCode:
    """Create a short-lived 6-digit code an enrolled member shares with a device.

    The code grants ``member_id``/``role`` to whichever device redeems it within
    the TTL. A fresh unused code is chosen (retried on the rare collision with a
    still-live code).
    """
    created = now or datetime.now(UTC)
    code = _new_pairing_code()
    # Avoid colliding with a still-live (unconsumed, unexpired) code.
    while True:
        existing = store.get_pairing_code(code)
        if existing is None or _is_spent(existing, created):
            break
        code = _new_pairing_code()
    pairing = PairingCode(
        code=code,
        family_id=family_id,
        member_id=member_id,
        role=role,
        label=label,
        created_at=created,
        expires_at=created + PAIRING_CODE_TTL,
    )
    store.put_pairing_code(pairing)
    return pairing


def redeem_pairing_code(
    store: TokenStore,
    code: str,
    *,
    secret: str,
    label: str = "",
    now: datetime | None = None,
) -> MintedToken:
    """Exchange a valid pairing code for a freshly minted device token.

    Validates the code (exists, not consumed, not expired, under the attempt cap),
    records the attempt, consumes the code on success, and mints a device token
    for the redeeming device. Raises :class:`PairingError` on any invalid state
    (opaque to the caller — the handler returns a generic failure).
    """
    moment = now or datetime.now(UTC)
    pairing = store.get_pairing_code(code)
    if pairing is None:
        raise PairingError("invalid pairing code")
    if pairing.attempts >= PAIRING_MAX_ATTEMPTS:
        raise PairingError("invalid pairing code")
    # Count this attempt before deciding, so a wrong/expired try still burns down
    # the cap (cheap accident guard).
    store.record_pairing_attempt(code)
    if pairing.consumed_at is not None:
        raise PairingError("invalid pairing code")
    if moment >= pairing.expires_at:
        raise PairingError("invalid pairing code")

    store.consume_pairing_code(code)
    return mint_device_token(
        store,
        family_id=pairing.family_id,
        member_id=pairing.member_id,
        role=pairing.role,
        label=label or pairing.label,
        secret=secret,
        now=moment,
    )


def _is_spent(pairing: PairingCode, now: datetime) -> bool:
    """Whether a pairing code is consumed or expired (free to reuse the digits)."""
    return pairing.consumed_at is not None or now >= pairing.expires_at


__all__ = [
    "PAIRING_CODE_TTL",
    "PAIRING_MAX_ATTEMPTS",
    "MintedToken",
    "PairingError",
    "Principal",
    "create_pairing_code",
    "mint_device_token",
    "redeem_pairing_code",
    "resolve_token",
]
