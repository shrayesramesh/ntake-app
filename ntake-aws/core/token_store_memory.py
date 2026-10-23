"""The in-memory identity store — the fast, networkless test double (AWS_LLD §5).

Dict-backed :class:`core.token_store.TokenStore`, the Tier-1 double for the
authorizer + pairing flows (the DynamoDB impl lands in the adapters layer for
Tier 2). Value semantics match the repository double: reads return deep copies,
writes store copies, so a caller mutating a returned DTO can't reach into the
store (mirroring DynamoDB's by-value items).
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from core.schemas import DeviceToken, PairingCode


class InMemoryTokenStore:
    """Dict-backed :class:`core.token_store.TokenStore` (unit-test double)."""

    def __init__(self) -> None:
        self._tokens: dict[str, DeviceToken] = {}  # token_hash -> DeviceToken
        self._codes: dict[str, PairingCode] = {}  # code -> PairingCode

    # --- device tokens ------------------------------------------------------

    def get_device_token(self, token_hash: str) -> DeviceToken | None:
        tok = self._tokens.get(token_hash)
        return copy.deepcopy(tok) if tok is not None else None

    def put_device_token(self, token: DeviceToken) -> None:
        self._tokens[token.token_hash] = copy.deepcopy(token)

    def list_device_tokens_for_member(self, member_id: str) -> list[DeviceToken]:
        return [
            copy.deepcopy(t) for t in self._tokens.values() if t.member_id == member_id
        ]

    def revoke_device_token(self, token_hash: str) -> None:
        tok = self._tokens.get(token_hash)
        if tok is not None and tok.revoked_at is None:
            tok.revoked_at = datetime.now(UTC)

    # --- pairing codes ------------------------------------------------------

    def get_pairing_code(self, code: str) -> PairingCode | None:
        pc = self._codes.get(code)
        return copy.deepcopy(pc) if pc is not None else None

    def put_pairing_code(self, pairing: PairingCode) -> None:
        self._codes[pairing.code] = copy.deepcopy(pairing)

    def consume_pairing_code(self, code: str) -> None:
        pc = self._codes.get(code)
        if pc is not None and pc.consumed_at is None:
            pc.consumed_at = datetime.now(UTC)

    def record_pairing_attempt(self, code: str) -> None:
        pc = self._codes.get(code)
        if pc is not None:
            pc.attempts += 1
