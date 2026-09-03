"""Device-token generation and hashing (Phase 2, ACCESS / DESIGN §2).

Tokens are high-entropy random secrets, so we hash with HMAC-SHA256 over a
per-install secret (dependency-free, correct for random tokens — a slow password
KDF is unnecessary). The server stores only the hash; the plaintext is shown once
at generation. Helpers take the secret as an argument to stay pure/testable;
``token_secret()`` resolves it from the environment for the app path.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def generate_token() -> str:
    """A new high-entropy URL-safe device token (plaintext, shown once)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str, *, secret: str) -> str:
    """HMAC-SHA256 of ``token`` under ``secret``, as hex. Deterministic."""
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def verify_token(token: str, token_hash: str, *, secret: str) -> bool:
    """Constant-time check that ``token`` hashes to ``token_hash`` under secret."""
    return hmac.compare_digest(hash_token(token, secret=secret), token_hash)


def token_secret() -> str:
    """The per-install HMAC secret from the environment (app path).

    Required in production; raises if unset so a server never silently hashes
    tokens under an empty/guessable key. Tests pass ``secret=`` directly and do
    not call this.
    """
    secret = os.environ.get("NTAKE_TOKEN_SECRET")
    if not secret:
        raise RuntimeError(
            "NTAKE_TOKEN_SECRET is not set; required to hash/verify device tokens."
        )
    return secret
