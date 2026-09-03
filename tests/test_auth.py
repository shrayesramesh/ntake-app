"""Phase 2, checkpoint 3 — request authentication (ACCESS-2, SAFE-1).

Every request carries a device token as ``Authorization: Bearer <token>``. The
server hashes it, looks up an *active* (revoked_at IS NULL) DeviceToken, and
resolves the member + role. No token / unknown / revoked -> 401. Tailscale is
the perimeter; this token is intra-family identity.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import DeviceToken, Family, Member
from app.tokens import generate_token, hash_token

SECRET = "test-token-secret"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setenv("NTAKE_TOKEN_SECRET", SECRET)


def _enroll(session, *, revoked: bool = False) -> str:
    """Create a family+member+device token; return the plaintext token."""
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    fam = Family(name="Fam", timezone="America/New_York")
    session.add(fam)
    session.commit()
    m = Member(family_id=fam.id, display_name="Adult", role="adult", created_at=now)
    session.add(m)
    session.commit()

    token = generate_token()
    session.add(
        DeviceToken(
            member_id=m.id,
            token_hash=hash_token(token, secret=SECRET),
            label="phone",
            created_at=now,
            revoked_at=now if revoked else None,
        )
    )
    session.commit()
    return token


def test_events_rejects_missing_token(client):
    r = client.get("/events")
    assert r.status_code == 401


def test_events_rejects_unknown_token(client):
    r = client.get("/events", headers={"Authorization": f"Bearer {generate_token()}"})
    assert r.status_code == 401


def test_events_rejects_revoked_token(client, session):
    token = _enroll(session, revoked=True)
    r = client.get("/events", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_events_accepts_valid_token(client, session):
    token = _enroll(session)
    r = client.get("/events", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == []


def test_health_is_open(client):
    # Liveness must not require auth.
    assert client.get("/health").status_code == 200


def test_events_rejects_empty_bearer(client):
    # "Bearer" with no token value → 401 (not a 500).
    r = client.get("/events", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_events_rejects_token_whose_member_was_removed(client, session):
    from app.models import Member

    token = _enroll(session)
    # Remove the member the token points at; the token is now orphaned.
    member = session.query(Member).one()
    session.delete(member)
    session.commit()

    r = client.get("/events", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_stream_auth_accepts_query_token(session, monkeypatch):
    """EventSource can't send headers, so stream auth accepts ?token= too.

    Tested at the dependency level: a live 200 SSE stream can't be read through
    the TestClient (the infinite generator blocks), so we exercise the auth unit
    directly rather than the socket.
    """
    from app.auth import current_member_stream

    monkeypatch.setenv("NTAKE_TOKEN_SECRET", SECRET)
    token = _enroll(session)
    member = current_member_stream(authorization=None, token=token, session=session)
    assert member is not None


def test_stream_auth_accepts_header(session, monkeypatch):
    from app.auth import current_member_stream

    monkeypatch.setenv("NTAKE_TOKEN_SECRET", SECRET)
    token = _enroll(session)
    member = current_member_stream(
        authorization=f"Bearer {token}", token=None, session=session
    )
    assert member is not None


def test_stream_auth_rejects_missing_and_bad(session, monkeypatch):
    import pytest
    from fastapi import HTTPException

    from app.auth import current_member_stream
    from app.tokens import generate_token

    monkeypatch.setenv("NTAKE_TOKEN_SECRET", SECRET)
    with pytest.raises(HTTPException):
        current_member_stream(authorization=None, token=None, session=session)
    with pytest.raises(HTTPException):
        current_member_stream(
            authorization=None, token=generate_token(), session=session
        )
