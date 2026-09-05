"""Phase 2, checkpoint 1 — device-token hashing.

Tokens are high-entropy random secrets (not user passwords), so an HMAC-SHA256
over a per-install secret is the right, dependency-free choice (a slow password
KDF like bcrypt/argon2 is unnecessary for random tokens). The server stores only
the hash (DESIGN §2); the plaintext is shown once at generation and never kept.

The helper takes the secret as an argument so it is pure and testable; the app
resolves the secret from the environment via ``token_secret()``.
"""

from __future__ import annotations

import pytest

from app.identity.tokens import generate_token, hash_token, token_secret, verify_token

SECRET = "test-secret-key"


def test_generate_token_is_long_and_random():
    a = generate_token()
    b = generate_token()
    assert a != b
    assert len(a) >= 32  # token_urlsafe(32) → ~43 chars


def test_hash_is_deterministic_for_same_token_and_secret():
    tok = generate_token()
    assert hash_token(tok, secret=SECRET) == hash_token(tok, secret=SECRET)


def test_hash_differs_by_secret():
    tok = generate_token()
    assert hash_token(tok, secret=SECRET) != hash_token(tok, secret="other-secret")


def test_hash_does_not_contain_plaintext():
    tok = generate_token()
    h = hash_token(tok, secret=SECRET)
    assert tok not in h


def test_verify_accepts_matching_token():
    tok = generate_token()
    h = hash_token(tok, secret=SECRET)
    assert verify_token(tok, h, secret=SECRET) is True


def test_verify_rejects_wrong_token():
    h = hash_token(generate_token(), secret=SECRET)
    assert verify_token(generate_token(), h, secret=SECRET) is False


def test_verify_rejects_wrong_secret():
    tok = generate_token()
    h = hash_token(tok, secret=SECRET)
    assert verify_token(tok, h, secret="other-secret") is False


def test_token_secret_returns_env_value(monkeypatch):
    monkeypatch.setenv("NTAKE_TOKEN_SECRET", "from-env")
    assert token_secret() == "from-env"


def test_token_secret_raises_when_unset(monkeypatch):
    monkeypatch.delenv("NTAKE_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        token_secret()
