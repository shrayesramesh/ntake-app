"""Device-token generation + hashing (core/tokens.py).

HMAC-SHA256 over a per-install secret; the server stores only the hash. In the
AWS build the secret source becomes Secrets Manager (AWS_LLD §5.1), but the pure
hashing helpers here are unchanged and tested with an explicit ``secret=``.
"""

from __future__ import annotations

import pytest

from core.tokens import generate_token, hash_token, token_secret, verify_token

SECRET = "unit-test-secret"


def test_generate_token_is_high_entropy_and_unique() -> None:
    a, b = generate_token(), generate_token()
    assert a != b
    assert len(a) >= 32  # token_urlsafe(32) -> ~43 chars


def test_hash_token_is_deterministic_and_hex() -> None:
    h1 = hash_token("tok", secret=SECRET)
    h2 = hash_token("tok", secret=SECRET)
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)


def test_hash_differs_by_token_and_by_secret() -> None:
    assert hash_token("a", secret=SECRET) != hash_token("b", secret=SECRET)
    assert hash_token("a", secret=SECRET) != hash_token("a", secret="other")


def test_verify_token_true_only_for_matching_hash() -> None:
    h = hash_token("correct", secret=SECRET)
    assert verify_token("correct", h, secret=SECRET) is True
    assert verify_token("wrong", h, secret=SECRET) is False


def test_token_secret_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTAKE_TOKEN_SECRET", "from-env")
    assert token_secret() == "from-env"


def test_token_secret_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTAKE_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        token_secret()
