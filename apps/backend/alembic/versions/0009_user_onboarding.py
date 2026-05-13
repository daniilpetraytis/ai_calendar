"""Add users.onboarded_at to track first-time onboarding completion.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.add_column(
        "users",
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
    )

def downgrade():
    op.drop_column("users", "onboarded_at")
