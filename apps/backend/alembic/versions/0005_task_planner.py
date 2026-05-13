"""Task planner: extend tasks, add dependencies, user preferences, and scheduling runs.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.add_column(
        "tasks",
        sa.Column(
            "focus_required",
            sa.String(length=20),
            nullable=False,
            server_default="shallow",
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "splittable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "min_chunk_minutes",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("recurrence_rule", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "auto_scheduled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("location", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("category", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tasks_user_status",
        "tasks",
        ["user_id", "status"],
    )

    op.create_table(
        "task_dependencies",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_task_dependencies_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_id"],
            ["tasks.id"],
            name=op.f("fk_task_dependencies_depends_on_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "task_id", "depends_on_id", name=op.f("pk_task_dependencies")
        ),
    )
    op.create_index(
        "ix_task_dependencies_depends_on_id",
        "task_dependencies",
        ["depends_on_id"],
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "working_hours",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "focus_windows",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "min_break_minutes",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
        sa.Column(
            "max_continuous_work_minutes",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column(
            "auto_schedule_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "buffer_after_meeting_minutes",
            sa.Integer(),
            nullable=False,
            server_default="15",
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
            name=op.f("fk_user_preferences_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_preferences")),
    )

    op.create_table(
        "scheduling_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "output_changes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "applied",
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_scheduling_runs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_scheduling_runs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduling_runs")),
    )
    op.create_index(
        "ix_scheduling_runs_user_created",
        "scheduling_runs",
        ["user_id", "created_at"],
    )

def downgrade():
    op.drop_index(
        "ix_scheduling_runs_user_created", table_name="scheduling_runs"
    )
    op.drop_table("scheduling_runs")
    op.drop_table("user_preferences")
    op.drop_index(
        "ix_task_dependencies_depends_on_id", table_name="task_dependencies"
    )
    op.drop_table("task_dependencies")
    op.drop_index("ix_tasks_user_status", table_name="tasks")
    op.drop_column("tasks", "completed_at")
    op.drop_column("tasks", "estimated_minutes")
    op.drop_column("tasks", "category")
    op.drop_column("tasks", "location")
    op.drop_column("tasks", "auto_scheduled")
    op.drop_column("tasks", "recurrence_rule")
    op.drop_column("tasks", "min_chunk_minutes")
    op.drop_column("tasks", "splittable")
    op.drop_column("tasks", "focus_required")
