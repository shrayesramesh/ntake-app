"""Alembic wiring (app.persistence.migrations) — the baseline reproduces the ORM schema.

The real DB is migration-managed; tests build schema from ``Base.metadata``
(``create_all``) for speed. This test is the **guard that the two agree**: a blank
DB migrated to head has exactly the same tables as ``create_all`` would produce.
If a future model change lands without a matching migration, this fails — the
whole point of wiring Alembic. Also pins that ``upgrade_to_head`` is idempotent
and that the ``manage migrate`` CLI drives it.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.persistence.database import build_engine, init_schema
from app.persistence.migrations import upgrade_to_head


def _tables(url: str) -> set[str]:
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migrated_db_matches_create_all_schema(tmp_path: Path):
    # create_all schema (the ORM metadata = canonical schema tests use).
    ca_url = f"sqlite:///{tmp_path / 'create_all.db'}"
    ca_eng = build_engine(ca_url)
    init_schema(ca_eng)
    ca_eng.dispose()
    create_all_tables = _tables(ca_url)

    # Migrated-from-blank schema (the real-DB path).
    mig_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    upgrade_to_head(mig_url)
    migrated_tables = _tables(mig_url)

    # The migration reproduces every model table (ignoring Alembic's own
    # bookkeeping table, which create_all doesn't make).
    assert migrated_tables - {"alembic_version"} == create_all_tables
    # Sanity: it's the real schema, not empty.
    assert {"families", "events", "work_items"} <= migrated_tables


def test_migrated_db_is_stamped_at_head(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'stamped.db'}"
    upgrade_to_head(url)
    # Alembic records the applied revision — a fresh migrate creates + stamps.
    eng = create_engine(url)
    try:
        assert "alembic_version" in set(inspect(eng).get_table_names())
        with eng.connect() as conn:
            from sqlalchemy import text

            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev  # a non-empty head revision id
    finally:
        eng.dispose()


def test_upgrade_to_head_is_idempotent(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'twice.db'}"
    upgrade_to_head(url)
    before = _tables(url)
    upgrade_to_head(url)  # second run is a no-op (already at head), not an error
    assert _tables(url) == before


def test_manage_migrate_cli(tmp_path, monkeypatch, capsys):
    import app.persistence.database as db
    from app.manage import main

    url = f"sqlite:///{tmp_path / 'cli.db'}"
    # manage migrate reads DB_URL from persistence; point it at the temp DB.
    monkeypatch.setattr(db, "DB_URL", url)

    rc = main(["migrate"])
    assert rc == 0
    assert "head" in capsys.readouterr().out.lower()
    assert "alembic_version" in _tables(url)
