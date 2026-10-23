"""Auth + pairing handler logic — pure, over the ``TokenStore`` seam (§5).

The decision logic behind the authorizer and the pairing endpoints, kept out of
the Lambda shells so it is Tier-1-testable with no event envelope. Thin wrappers
over ``core.identity``:

* **authorize** — the REQUEST-authorizer decision: a presented token (bearer or
  ``?token=``) → an allow/deny + the resolved principal context the handlers read.
* **create_pairing** — an enrolled member mints a 6-digit code for a new device.
* **redeem_pairing** — the public exchange: a code → a fresh device token.

Token extraction from the two carriers (``Authorization: Bearer`` header and the
``?token=`` query for the WebSocket ``$connect``) lives here too, as a pure parse.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.identity import (
    MintedToken,
    PairingError,
    Principal,
    create_pairing_code,
    redeem_pairing_code,
    resolve_token,
)
from core.schemas import PairingCode
from core.token_store import TokenStore


@dataclass(frozen=True)
class AuthDecision:
    """The authorizer result: allow + the principal context, or deny."""

    allowed: bool
    principal: Principal | None = None


def extract_token(
    *, authorization_header: str | None = None, query_token: str | None = None
) -> str | None:
    """Pull the plaintext token from a ``Bearer`` header or a ``?token=`` query.

    The HTTP API sends ``Authorization: Bearer <token>``; the WebSocket
    ``$connect`` can't set headers so it uses ``?token=`` (AWS_LLD §4.1/§5.2). A
    bare header value without the ``Bearer`` scheme is still accepted (lenient).
    """
    if authorization_header:
        parts = authorization_header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization_header.strip()
    if query_token:
        return query_token.strip()
    return None


def authorize(store: TokenStore, plaintext: str | None, *, secret: str) -> AuthDecision:
    """Resolve a token to an allow+principal, or a uniform deny (AWS_LLD §5.2)."""
    principal = resolve_token(store, plaintext, secret=secret)
    if principal is None:
        return AuthDecision(allowed=False)
    return AuthDecision(allowed=True, principal=principal)


def create_pairing(
    store: TokenStore, creator: Principal, *, label: str = ""
) -> PairingCode:
    """An enrolled member creates a pairing code granting their own family/role.

    The new device inherits the creator's ``family_id``/``member_id``/``role`` —
    v1 pairs a device to the creating member (per-member device enrollment). A
    distinct member/role grant is a later admin affordance.
    """
    return create_pairing_code(
        store,
        family_id=creator.family_id,
        member_id=creator.member_id,
        role=creator.role,
        label=label,
    )


def redeem_pairing(
    store: TokenStore, code: str, *, secret: str, label: str = ""
) -> MintedToken:
    """Exchange a code for a device token, or raise :class:`PairingError`."""
    return redeem_pairing_code(store, code, secret=secret, label=label)


__all__ = [
    "AuthDecision",
    "PairingError",
    "authorize",
    "create_pairing",
    "extract_token",
    "redeem_pairing",
]
