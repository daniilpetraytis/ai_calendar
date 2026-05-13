"""Add event categories, per-user category definitions, and correction history.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.add_column(
        "events", sa.Column("category", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "events", sa.Column("category_source", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "events", sa.Column("category_confidence", sa.Float(), nullable=True)
    )
    op.create_index(
        "ix_events_user_category", "events", ["user_id", "category"]
    )

    op.create_table(
        "category_definitions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column(
            "color",
            sa.String(length=7),
            nullable=False,
            server_default="#9ca3af",
        ),
        sa.Column("emoji", sa.String(length=8), nullable=True),
        sa.Column("goal_minutes_per_week", sa.Integer(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
            name=op.f("fk_category_definitions_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_category_definitions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "name", name=op.f("pk_category_definitions")
        ),
    )

    op.create_table(
        "category_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_title", sa.String(length=500), nullable=False),
        sa.Column("event_description", sa.Text(), nullable=True),
        sa.Column("event_location", sa.String(length=500), nullable=True),
        sa.Column("predicted", sa.String(length=50), nullable=True),
        sa.Column("predicted_source", sa.String(length=20), nullable=True),
        sa.Column("predicted_confidence", sa.Float(), nullable=True),
        sa.Column("corrected", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_category_corrections_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_category_corrections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_category_corrections_event_id_events"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_corrections")),
    )
    op.create_index(
        "ix_category_corrections_user_created",
        "category_corrections",
        ["user_id", "created_at"],
    )

def downgrade():
    op.drop_index(
        "ix_category_corrections_user_created", table_name="category_corrections"
    )
    op.drop_table("category_corrections")
    op.drop_table("category_definitions")
    op.drop_index("ix_events_user_category", table_name="events")
    op.drop_column("events", "category_confidence")
    op.drop_column("events", "category_source")
    op.drop_column("events", "category")
