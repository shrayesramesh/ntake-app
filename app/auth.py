"""Request authentication (Phase 2, ACCESS-2 / SAFE-1).

A FastAPI dependency that resolves the ``Authorization: Bearer <token>`` header
to the enrolled :class:`~app.models.Member`, or raises 401. The presented token
is hashed (HMAC via the per-install secret) and matched against an *active*
DeviceToken (``revoked_at IS NULL``). Handlers depending on ``current_member``
receive identity + role for attribution and SAFE-2 gating.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import DeviceToken, Member
from app.tokens import hash_token, token_secret

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing or invalid device token.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED
    token = authorization[len("bearer ") :].strip()
    if not token:
        raise _UNAUTHORIZED
    return token


def _member_for_token(token: str, session: Session) -> Member:
    """Resolve a plaintext token to its active member, or raise 401."""
    token_hash = hash_token(token, secret=token_secret())
    device = session.scalar(
        select(DeviceToken).where(
            DeviceToken.token_hash == token_hash,
            DeviceToken.revoked_at.is_(None),
        )
    )
    if device is None:
        raise _UNAUTHORIZED
    member = session.get(Member, device.member_id)
    if member is None:  # token's member was removed
        raise _UNAUTHORIZED
    return member


def current_member(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Member:
    """Resolve the caller's Member from the ``Authorization`` bearer header, or 401.

    Matches only active tokens (``revoked_at IS NULL``); unknown or revoked
    tokens are indistinguishable to the caller (both 401).
    """
    return _member_for_token(_extract_bearer(authorization), session)


def current_member_stream(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> Member:
    """Auth for the SSE stream: header **or** ``?token=`` query param.

    ``EventSource`` cannot set an Authorization header, so the stream endpoint
    (only) also accepts the token as a query param. Scoped to the stream so
    regular endpoints don't accept tokens in URLs (which get logged).
    """
    if authorization:
        return _member_for_token(_extract_bearer(authorization), session)
    if token:
        return _member_for_token(token, session)
    raise _UNAUTHORIZED
