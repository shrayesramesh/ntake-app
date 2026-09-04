"""Alembic environment — driven by app.migrations (no alembic.ini).

The DB URL comes from the in-code ``Config`` (``sqlalchemy.url``, set by
``app.migrations.make_alembic_config``) when provided, else from
``CALENDAR_DB_URL`` via ``app.db.DB_URL`` — one source of truth. ``target_metadata``
is ``app.db.Base.metadata`` (models imported so every table is registered), which
is what ``--autogenerate`` diffs against.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 — register all mappers on Base.metadata
from app.db import DB_URL, Base

config = context.config

# URL precedence: explicit Config option (app.migrations) → CALENDAR_DB_URL.
_url = config.get_main_option("sqlalchemy.url") or DB_URL

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL against a URL (no live connection) — ``--sql`` mode."""
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,  # SQLite-safe ALTERs (batch mode)
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection built from the resolved URL."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-safe ALTERs (batch mode)
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
