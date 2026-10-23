"""The identity persistence seam — device tokens + pairing codes (AWS_LLD §5).

A seam deliberately **separate** from :class:`core.repository.Repository`: the
family repository is family-partition-scoped (``FAM#<fam>`` is the partition
dimension), whereas identity records are top-level items keyed by their own hash
or code (``TOK#<hash>`` / ``PAIR#<code>``, AWS_LLD §1.2/§5). Keeping them apart
leaves the family repository cohesive and lets the authorizer Lambda's IAM scope
to just the identity items — it never needs family-data access to resolve a
token.

Two record types:

* **Device token** (``TOK#<hash>``): the durable device credential. Only the
  **hash** is stored (``core.tokens.hash_token``); plaintext is shown once at
  mint and never persisted. The authorizer hashes a presented token, looks it up
  here, and (if present and not revoked) resolves the member/family/role.
* **Pairing code** (``PAIR#<code>``): a short-lived 6-digit enrollment code an
  enrolled member creates so a new device can exchange it for a full-entropy
  device token (``POST /pair``) — no long token ever copied by a human. Single-
  use + short-TTL + attempt-capped (cheap accident guards; this is a private
  family app, not a public high-traffic service — abuse hardening is deliberately
  light, see the repo's threat-model note).

Like :class:`Repository`, there is **no ``commit``** — each method is one atomic
op (one ``PutItem``/``GetItem``/``UpdateItem`` in the Dynamo impl). Pure key
composers live here as the single source of identity-key knowledge, reused
byte-for-byte by the Dynamo impl.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.schemas import DeviceToken, PairingCode

# --- key composition (pure; the single source of identity-key knowledge) ----

TOK_PREFIX = "TOK#"
PAIR_PREFIX = "PAIR#"


def token_pk(token_hash: str) -> str:
    """The partition key of a device-token item (AWS_LLD §1.2: ``TOK#<hash>``)."""
    return f"{TOK_PREFIX}{token_hash}"


def pairing_pk(code: str) -> str:
    """The partition key of a pairing-code item (AWS_LLD §5.4: ``PAIR#<code>``)."""
    return f"{PAIR_PREFIX}{code}"


# --- the identity protocol (AWS_LLD §5) ------------------------------------


@runtime_checkable
class TokenStore(Protocol):
    """The device-token + pairing-code store the authorizer and pairing use.

    Reads return DTOs (or ``None`` on a miss); writes are void and atomic. No
    family scoping — identity items are top-level (keyed by hash/code).
    """

    # device tokens
    def get_device_token(self, token_hash: str) -> DeviceToken | None: ...
    def put_device_token(self, token: DeviceToken) -> None: ...
    def list_device_tokens_for_member(self, member_id: str) -> list[DeviceToken]: ...
    def revoke_device_token(self, token_hash: str) -> None: ...

    # pairing codes
    def get_pairing_code(self, code: str) -> PairingCode | None: ...
    def put_pairing_code(self, pairing: PairingCode) -> None: ...
    def consume_pairing_code(self, code: str) -> None: ...
    def record_pairing_attempt(self, code: str) -> None: ...
