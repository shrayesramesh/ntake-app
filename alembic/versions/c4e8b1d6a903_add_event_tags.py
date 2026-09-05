"""Add shared tags to events.

Revision ID: c4e8b1d6a903
Revises: 7f6a4d2b9e31
Create Date: 2026-09-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4e8b1d6a903"
down_revision = "7f6a4d2b9e31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.add_column(
            sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.drop_column("tags")
