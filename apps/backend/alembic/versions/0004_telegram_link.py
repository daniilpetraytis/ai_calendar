"""Add Telegram user linking: users.telegram_user_id and one-time link tokens.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.add_column(
        "users", sa.Column("telegram_user_id", sa.BigInteger(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_users_telegram_user_id", "users", ["telegram_user_id"]
    )
    op.create_index(
        "ix_users_telegram_user_id", "users", ["telegram_user_id"]
    )

    op.create_table(
        "telegram_link_tokens",
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_telegram_link_tokens_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_telegram_link_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_telegram_link_tokens")),
    )
    op.create_index(
        "ix_telegram_link_tokens_user_id",
        "telegram_link_tokens",
        ["user_id"],
    )

def downgrade():
    op.drop_index(
        "ix_telegram_link_tokens_user_id", table_name="telegram_link_tokens"
    )
    op.drop_table("telegram_link_tokens")
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_constraint("uq_users_telegram_user_id", "users", type_="unique")
    op.drop_column("users", "telegram_user_id")
