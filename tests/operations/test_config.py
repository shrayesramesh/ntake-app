"""Phase 2, checkpoint 2 — config loading + DB seeding.

The out-of-repo config (family + members, no secrets) is the editing surface;
on startup it seeds the DB (option B — keeps the members table populated so the
Phase 3 author FK is valid). Tests pass a path/dict directly — no external dir,
no env dependency (the env only supplies the default path for the app).
"""

from __future__ import annotations

import pytest

from app.config import FamilyConfig, config_path, load_config, seed_from_config
from app.persistence.models import Family, Member
from tests.fixtures.alex_sam_household import ALEX_SAM_TOML

SAMPLE = """
[family]
name = "Ramesh"
timezone = "America/New_York"

[[members]]
display_name = "Adult One"
role = "adult"

[[members]]
display_name = "Wall Display"
role = "child"
"""


def _write(tmp_path, text: str):
    p = tmp_path / "family.toml"
    p.write_text(text)
    return p


def test_load_config_parses_family_and_members(tmp_path):
    cfg = load_config(_write(tmp_path, SAMPLE))
    assert isinstance(cfg, FamilyConfig)
    assert cfg.family.name == "Ramesh"
    assert cfg.family.timezone == "America/New_York"
    assert [m.display_name for m in cfg.members] == ["Adult One", "Wall Display"]


def test_alex_sam_household_config_loads(tmp_path):
    cfg = load_config(_write(tmp_path, ALEX_SAM_TOML))

    assert cfg.family.name == "Alex and Sam Household"
    assert cfg.family.timezone == "America/New_York"
    assert [(member.display_name, member.role) for member in cfg.members] == [
        ("Alex", "adult"),
        ("Sam", "child"),
    ]
    assert [m.role for m in cfg.members] == ["adult", "child"]


def test_load_config_rejects_bad_role(tmp_path):
    bad = SAMPLE.replace('role = "child"', 'role = "wizard"')
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, bad))


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_seed_creates_family_and_members(session, tmp_path):
    cfg = load_config(_write(tmp_path, SAMPLE))
    seed_from_config(session, cfg)

    fams = session.query(Family).all()
    assert len(fams) == 1
    assert fams[0].name == "Ramesh"
    members = session.query(Member).order_by(Member.display_name).all()
    assert [m.display_name for m in members] == ["Adult One", "Wall Display"]
    assert {m.role for m in members} == {"adult", "child"}


def test_seed_is_idempotent(session, tmp_path):
    cfg = load_config(_write(tmp_path, SAMPLE))
    seed_from_config(session, cfg)
    seed_from_config(session, cfg)  # second startup must not duplicate

    assert session.query(Family).count() == 1
    assert session.query(Member).count() == 2


def test_seed_adds_new_member_on_reload(session, tmp_path):
    seed_from_config(session, load_config(_write(tmp_path, SAMPLE)))
    grown = SAMPLE + '\n[[members]]\ndisplay_name = "Adult Two"\nrole = "adult"\n'
    seed_from_config(session, load_config(_write(tmp_path, grown)))

    names = {m.display_name for m in session.query(Member).all()}
    assert names == {"Adult One", "Wall Display", "Adult Two"}


def test_config_path_uses_env_then_default(monkeypatch):
    monkeypatch.setenv("NTAKE_CONFIG", "/tmp/custom/family.toml")
    assert str(config_path()) == "/tmp/custom/family.toml"

    monkeypatch.delenv("NTAKE_CONFIG", raising=False)
    # Default lives under the user's config dir; just assert the filename.
    assert config_path().name == "family.toml"


def test_app_startup_seeds_members_from_config(tmp_path, monkeypatch):
    """Booting the app with NTAKE_CONFIG set seeds members via the lifespan."""
    from fastapi.testclient import TestClient

    import app.main as main
    import app.persistence.database as db
    from app.persistence.database import build_engine

    cfg_file = _write(tmp_path, SAMPLE)
    monkeypatch.setenv("NTAKE_CONFIG", str(cfg_file))
    # Fresh DB so seeding is observable in isolation.
    fresh = build_engine(f"sqlite:///{tmp_path / 'boot.db'}")
    monkeypatch.setattr(db, "engine", fresh)
    monkeypatch.setattr(db, "SessionLocal", db.make_session_factory(fresh))

    with TestClient(main.app):  # enters lifespan → init_schema + seed_from_config
        session = db.SessionLocal()
        try:
            names = {m.display_name for m in session.query(Member).all()}
        finally:
            session.close()

    assert names == {"Adult One", "Wall Display"}
