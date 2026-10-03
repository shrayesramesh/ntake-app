"""Server-side id minting — ULID strings, stdlib-only (AWS_LLD §1).

Ids are **ULID strings minted server/Lambda-side at write time** (the client
supplies neither ids nor stored timestamps — AWS_LLD preamble). The DTOs carry
these as **prefix-free** strings; the repository adds the ``FAM#``/``WI#``/…
type prefix at the key boundary (``core.repository``), never the DTO.

Why hand-rolled (not a ``ulid`` dependency): a ULID is a 48-bit millisecond
timestamp + 80 bits of randomness, rendered in Crockford base32 — 26 chars,
lexicographically sortable by creation time. That is a handful of stdlib lines,
and YAGNI says don't pin a dependency for it. This lives in ``core`` (not the
adapter) because id minting is a domain concern shared by every write path and
must stay importable without ``boto3`` (the engine boundary).
"""

from __future__ import annotations

import os
import time

# Crockford base32 alphabet (no I, L, O, U — the ULID spec's alphabet).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_LEN = 10  # 48-bit ms timestamp -> 10 base32 chars
_RAND_LEN = 16  # 80-bit randomness   -> 16 base32 chars


def _encode(value: int, length: int) -> str:
    chars = [""] * length
    for i in range(length - 1, -1, -1):
        chars[i] = _CROCKFORD[value & 0x1F]
        value >>= 5
    return "".join(chars)


def new_ulid() -> str:
    """Mint a new 26-char ULID string (time-ordered, prefix-free).

    The 48-bit millisecond timestamp sorts the first 10 chars by creation time;
    the remaining 16 chars are 80 bits of ``os.urandom`` entropy. Monotonicity
    within a single millisecond is not guaranteed (not needed — the GSIs sort by
    explicit status/position and TS keys, not by id), only global uniqueness.
    """
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits
    return _encode(ms, _TIME_LEN) + _encode(rand, _RAND_LEN)
