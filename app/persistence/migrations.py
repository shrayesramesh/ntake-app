"""Alembic wiring, in code — no ``alembic.ini``, no separate ``alembic`` CLI.

Migrations are the schema path for the **real** deployed DB; tests build a fresh
schema from the ORM metadata (``init_schema`` / ``create_all``) for speed. This
module is the glue: it builds an Alembic ``Config`` programmatically (pointing at
the ``alembic/`` script tree and injecting the DB URL) so the operator drives
migrations through ``python -m app.manage migrate`` instead of a standalone tool
with its own ini.

``env.py`` (in ``alembic/``) reads the URL this sets and targets
``app.persistence.database.Base.metadata`` for autogenerate. Keeping the
``Config`` here (not an ini) means one source of truth for the URL:
``CALENDAR_DB_URL`` via ``app.persistence.database``.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

# The alembic script tree lives at the repo root (sibling of app/), holding
# env.py + versions/. Resolve it relative to this file so it works regardless of
# the process's cwd (startup, CLI, tests).
_ALEMBIC_DIR = Path(__file__).resolve().parent.parent.parent / "alembic"


def make_alembic_config(url: str | None = None) -> Config:
    """Build an Alembic ``Config`` in code (no ini file).

    ``url`` overrides the DB URL; when omitted, ``env.py`` falls back to
    ``CALENDAR_DB_URL`` (via ``app.persistence.database.DB_URL``).
    Sets ``script_location`` to the
    ``alembic/`` tree so autogenerate/upgrade find env.py + versions/.
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    if url is not None:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def upgrade_to_head(url: str | None = None) -> None:
    """Run ``alembic upgrade head`` on ``url`` (or the default ``CALENDAR_DB_URL``).

    On a fresh DB this creates every table *via the migrations* and stamps it at
    the head revision, so the real DB is always Alembic-managed (no create_all /
    migration drift). Idempotent: a DB already at head is a no-op.
    """
    command.upgrade(make_alembic_config(url), "head")
