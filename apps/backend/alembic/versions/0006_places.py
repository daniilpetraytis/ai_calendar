"""Add per-user named places with at most one default place per user.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.create_table(
        "places",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
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
            name=op.f("fk_places_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_places_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_places")),
        sa.UniqueConstraint("user_id", "name", name="uq_places_user_name"),
    )
    op.create_index("ix_places_user", "places", ["user_id"])
    # Partial unique index: at most one default place per user.
    op.create_index(
        "ux_places_one_default_per_user",
        "places",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

def downgrade():
    op.drop_index("ux_places_one_default_per_user", table_name="places")
    op.drop_index("ix_places_user", table_name="places")
    op.drop_table("places")
