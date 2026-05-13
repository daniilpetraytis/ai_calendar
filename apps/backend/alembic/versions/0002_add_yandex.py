"""Add Yandex calendar provider and event source enum values.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.execute("ALTER TYPE integration_provider ADD VALUE IF NOT EXISTS 'yandex_calendar'")
    op.execute("ALTER TYPE event_source ADD VALUE IF NOT EXISTS 'yandex'")

def downgrade():
    pass
