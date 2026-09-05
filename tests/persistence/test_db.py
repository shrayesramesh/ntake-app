"""Engine durability settings (NFR-DURABILITY).

SQLite crash-safety: the app engine must run in **WAL** journal mode with
``synchronous=NORMAL`` — WAL gives a clean rollback on power loss (no
corruption), and NORMAL is the safe+fast pairing WAL is designed for. These are
set in ``build_engine``'s per-connection listener alongside ``foreign_keys=ON``.

WAL is a *persistent* database property, so the test uses a real file DB (it does
not apply to ``:memory:``); ``synchronous`` is per-connection, so we assert both
on a fresh connection from the engine.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.persistence.database import build_engine


def test_engine_uses_wal_and_synchronous_normal(tmp_path: Path):
    eng = build_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    try:
        with eng.connect() as conn:
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            synchronous = conn.execute(text("PRAGMA synchronous")).scalar()
        # WAL journal mode (persistent); synchronous NORMAL == 1.
        assert str(journal).lower() == "wal"
        assert synchronous == 1
    finally:
        eng.dispose()


def test_engine_still_enforces_foreign_keys(tmp_path: Path):
    # The durability pragmas must not displace the existing foreign_keys=ON.
    eng = build_engine(f"sqlite:///{tmp_path / 'fk.db'}")
    try:
        with eng.connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk == 1
    finally:
        eng.dispose()
