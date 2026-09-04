"""Phase 2, checkpoint 4 — the manage CLI (device-token enrollment).

Operator tool run on the home PC (no admin UI). Core logic is pure functions
taking a session so they unit-test against the in-memory fixture; a thin argparse
``main`` wraps them. gen-token stores only the hash and returns the plaintext
once (never persisted, never logged).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.manage import gen_token_for, list_tokens, revoke_token
from app.models import DeviceToken, Family, Member
from app.tokens import hash_token

SECRET = "test-manage-secret"


def _member(session, name="Shrayes") -> Member:
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    fam = session.query(Family).first()
    if fam is None:
        fam = Family(name="Fam", timezone="America/New_York")
        session.add(fam)
        session.commit()
    m = Member(family_id=fam.id, display_name=name, role="adult", created_at=now)
    session.add(m)
    session.commit()
    return m


def test_gen_token_returns_plaintext_and_stores_only_hash(session):
    m = _member(session)
    token = gen_token_for(session, "Shrayes", label="phone", secret=SECRET)

    assert isinstance(token, str) and len(token) >= 32
    dt = session.query(DeviceToken).one()
    assert dt.member_id == m.id
    assert dt.label == "phone"
    # Stored value is the hash, not the plaintext.
    assert dt.token_hash == hash_token(token, secret=SECRET)
    assert token not in dt.token_hash


def test_gen_token_unknown_member_raises(session):
    _member(session, "Shrayes")
    with pytest.raises(ValueError):
        gen_token_for(session, "Nobody", label="x", secret=SECRET)


def test_revoke_token_sets_revoked_at(session):
    _member(session)
    gen_token_for(session, "Shrayes", label="phone", secret=SECRET)
    dt = session.query(DeviceToken).one()
    assert dt.revoked_at is None

    revoke_token(session, dt.id)
    session.refresh(dt)
    assert dt.revoked_at is not None


def test_list_tokens_reports_status_without_secrets(session):
    _member(session)
    gen_token_for(session, "Shrayes", label="phone", secret=SECRET)
    rows = list_tokens(session)

    assert len(rows) == 1
    row = rows[0]
    assert row["member"] == "Shrayes"
    assert row["label"] == "phone"
    assert row["active"] is True
    # Never leak secrets in a listing.
    assert "token_hash" not in row
    assert "token" not in row


# --- CLI (main) dispatch --------------------------------------------------


@pytest.fixture()
def cli_db(tmp_path, monkeypatch):
    """Point app.manage.main at a fresh temp DB + a known token secret."""
    import app.db as db
    from app.db import build_engine, init_schema, make_session_factory

    monkeypatch.setenv("NTAKE_TOKEN_SECRET", SECRET)
    engine = build_engine(f"sqlite:///{tmp_path / 'manage.db'}")
    init_schema(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", factory)

    # Seed a member to enroll against.
    s = factory()
    fam = Family(name="Fam", timezone="America/New_York")
    s.add(fam)
    s.commit()
    s.add(
        Member(
            family_id=fam.id,
            display_name="Shrayes",
            role="adult",
            created_at=datetime.now(UTC),
        )
    )
    s.commit()
    s.close()
    return factory


def test_main_gen_token_prints_once_and_stores_hash(cli_db, capsys):
    from app.manage import main

    rc = main(["gen-token", "Shrayes", "--label", "Pixel"])
    assert rc == 0
    out = capsys.readouterr().out
    # The token is printed once; extract it and confirm it verifies against the
    # stored hash (and that we stored a hash, not the plaintext).
    printed = [ln.strip() for ln in out.splitlines() if ln.strip()]
    token_line = next(ln for ln in printed if len(ln) >= 32 and " " not in ln)
    dt = cli_db().query(DeviceToken).one()
    assert dt.token_hash == hash_token(token_line, secret=SECRET)


def test_main_unknown_member_returns_error(cli_db, capsys):
    from app.manage import main

    rc = main(["gen-token", "Ghost", "--label", "x"])
    assert rc == 1
    assert "No member" in capsys.readouterr().err


def test_main_list_and_revoke(cli_db, capsys):
    from app.manage import main

    assert main(["gen-token", "Shrayes", "--label", "Pixel"]) == 0
    capsys.readouterr()  # clear

    assert main(["list-tokens"]) == 0
    listing = capsys.readouterr().out
    assert "Shrayes" in listing and "active" in listing

    dt_id = cli_db().query(DeviceToken).one().id
    assert main(["revoke", str(dt_id)]) == 0
    assert "Revoked" in capsys.readouterr().out
    session = cli_db()
    assert session.get(DeviceToken, dt_id).revoked_at is not None


def test_main_backup_default_dest(cli_db, tmp_path, monkeypatch, capsys):
    # No --dest -> a timestamped file under ./backups/. Run in a temp cwd so the
    # backups/ dir doesn't land in the repo.
    from app.manage import main

    monkeypatch.chdir(tmp_path)
    rc = main(["backup"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "backups" in out
    written = list((tmp_path / "backups").glob("ntake-*.db"))
    assert len(written) == 1


def test_main_backup_writes_snapshot(cli_db, tmp_path, capsys):
    from sqlalchemy import select

    from app.manage import main

    dest = tmp_path / "cli-snapshot.db"
    rc = main(["backup", "--dest", str(dest)])
    assert rc == 0
    assert dest.exists()
    assert str(dest) in capsys.readouterr().out

    # The snapshot is a complete copy — the seeded family is present in it.
    from app.db import build_engine, make_session_factory

    beng = build_engine(f"sqlite:///{dest}")
    try:
        bs = make_session_factory(beng)()
        try:
            fams = bs.scalars(select(Family)).all()
            assert [f.name for f in fams] == ["Fam"]
        finally:
            bs.close()
    finally:
        beng.dispose()
