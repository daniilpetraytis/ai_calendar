"""Initial schema: tenants, users, integrations, events, tasks, biometrics, agent runs.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("external_auth_id", sa.String(length=200), nullable=True),
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_users_tenant_id_tenants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("external_auth_id", name=op.f("uq_users_external_auth_id")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    integration_provider = postgresql.ENUM(
        "google_calendar", "whoop", name="integration_provider", create_type=False
    )
    integration_provider.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM("google_calendar", "whoop", name="integration_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("account_email", sa.String(length=320), nullable=True),
        sa.Column("sync_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_integrations_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_integrations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint("user_id", "provider", name="uq_integrations_user_provider"),
    )

    event_source = postgresql.ENUM("google", "local", name="event_source", create_type=False)
    event_source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "source",
            postgresql.ENUM("google", "local", name="event_source", create_type=False),
            nullable=False,
            server_default="local",
        ),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("calendar_id", sa.String(length=200), nullable=True),
        sa.Column("etag", sa.String(length=200), nullable=True),
        sa.Column("is_movable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_events_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_events_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("user_id", "source", "external_id", name="uq_events_source_external"),
    )
    op.create_index("ix_events_user_start", "events", ["user_id", "start_at"])
    op.create_index(op.f("ix_events_external_id"), "events", ["external_id"])

    task_status = postgresql.ENUM(
        "pending", "scheduled", "done", "skipped", name="task_status", create_type=False
    )
    task_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("earliest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "scheduled", "done", "skipped", name="task_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("scheduled_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_tasks_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_tasks_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scheduled_event_id"], ["events.id"], name=op.f("fk_tasks_scheduled_event_id_events"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )

    op.create_table(
        "biometrics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM("google_calendar", "whoop", name="integration_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("recovery_score", sa.Integer(), nullable=True),
        sa.Column("hrv_rmssd_ms", sa.Float(), nullable=True),
        sa.Column("resting_heart_rate", sa.Integer(), nullable=True),
        sa.Column("sleep_performance", sa.Float(), nullable=True),
        sa.Column("strain", sa.Float(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_biometrics_snapshots_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_biometrics_snapshots_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biometrics_snapshots")),
        sa.UniqueConstraint("user_id", "date", "provider", name="uq_biometrics_user_date_provider"),
    )
    op.create_index("ix_biometrics_user_date", "biometrics_snapshots", ["user_id", "date"])

    agent_run_status = postgresql.ENUM(
        "running", "awaiting_approval", "completed", "rejected", "failed",
        name="agent_run_status", create_type=False,
    )
    agent_run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("running", "awaiting_approval", "completed", "rejected", "failed",
                            name="agent_run_status", create_type=False),
            nullable=False,
            server_default="running",
        ),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("assistant_message", sa.Text(), nullable=True),
        sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_agent_runs_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_agent_runs_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index("ix_agent_runs_user_status", "agent_runs", ["user_id", "status"])
    op.create_index(op.f("ix_agent_runs_thread_id"), "agent_runs", ["thread_id"])

def downgrade():
    op.drop_index(op.f("ix_agent_runs_thread_id"), table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_status", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_biometrics_user_date", table_name="biometrics_snapshots")
    op.drop_table("biometrics_snapshots")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_events_external_id"), table_name="events")
    op.drop_index("ix_events_user_start", table_name="events")
    op.drop_table("events")
    op.drop_table("integrations")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")

    for enum_name in ("agent_run_status", "task_status", "event_source", "integration_provider"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
