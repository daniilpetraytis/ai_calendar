"""Add daily_briefings table for morning/evening briefings and feedback.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.create_table(
        "daily_briefings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_band", sa.String(length=10), nullable=True),
        sa.Column("recovery_score", sa.Integer(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("feedback_score", sa.Integer(), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_daily_briefings_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_daily_briefings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_briefings")),
        sa.UniqueConstraint(
            "user_id", "date", "kind", name="uq_daily_briefings_user_date_kind"
        ),
    )
    op.create_index(
        "ix_daily_briefings_user_date",
        "daily_briefings",
        ["user_id", "date"],
    )

def downgrade():
    op.drop_index("ix_daily_briefings_user_date", table_name="daily_briefings")
    op.drop_table("daily_briefings")
