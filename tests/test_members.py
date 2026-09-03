"""Phase 2, checkpoint 1 — Member and DeviceToken models.

Per DESIGN §3: members carry a role (adult|child); device_tokens store the token
hash (unique), a label, and a nullable revoked_at (NULL = active).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import DeviceToken, Family, Member


def _family(session) -> Family:
    fam = Family(name="Ramesh", timezone="America/New_York")
    session.add(fam)
    session.commit()
    return fam


def test_member_roundtrip(session):
    fam = _family(session)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    m = Member(
        family_id=fam.id,
        display_name="Shrayes",
        role="adult",
        created_at=now,
    )
    session.add(m)
    session.commit()

    got = session.get(Member, m.id)
    assert got is not None
    assert got.display_name == "Shrayes"
    assert got.role == "adult"
    assert got.phone_number is None  # optional contact field


def test_device_token_roundtrip_and_active_by_default(session):
    fam = _family(session)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    m = Member(
        family_id=fam.id, display_name="Wall Display", role="child", created_at=now
    )
    session.add(m)
    session.commit()

    dt = DeviceToken(
        member_id=m.id,
        token_hash="deadbeef",
        label="iPad kiosk",
        created_at=now,
    )
    session.add(dt)
    session.commit()

    got = session.get(DeviceToken, dt.id)
    assert got is not None
    assert got.member_id == m.id
    assert got.label == "iPad kiosk"
    assert got.revoked_at is None  # NULL = active


def test_token_hash_is_unique(session):
    fam = _family(session)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    m = Member(family_id=fam.id, display_name="A", role="adult", created_at=now)
    session.add(m)
    session.commit()

    session.add(
        DeviceToken(member_id=m.id, token_hash="same", label="x", created_at=now)
    )
    session.commit()
    session.add(
        DeviceToken(member_id=m.id, token_hash="same", label="y", created_at=now)
    )
    with pytest.raises(IntegrityError):
        session.commit()
