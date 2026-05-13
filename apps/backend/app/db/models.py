"""SQLAlchemy ORM models for the AI Calendar database."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass

def _enum_values(enum_cls):
    """Return the list of string values for a ``StrEnum`` (used as a SQLAlchemy ``values_callable``)."""
    return [member.value for member in enum_cls]

class IntegrationProvider(StrEnum):
    """External provider for an Integration row."""
    YANDEX_CALENDAR = "yandex_calendar"
    WHOOP = "whoop"

class EventSource(StrEnum):
    """Origin of a calendar event row."""
    YANDEX = "yandex"
    LOCAL = "local"

class TaskStatus(StrEnum):
    """Lifecycle state of a user task."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    DONE = "done"
    SKIPPED = "skipped"

class AgentRunStatus(StrEnum):
    """Lifecycle state of an agent run / proposal."""
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"

class CategorySource(StrEnum):
    """Origin of an event's assigned category."""

    RULES = "rules"
    LLM = "llm"
    USER = "user"
    AGENT = "agent"

class Tenant(TimestampMixin, Base):
    """Top-level tenant grouping users into an organization or workspace."""
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="tenant", cascade="all, delete-orphan")

class User(TimestampMixin, Base):
    """End user with calendar, tasks, places, and integrations."""
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    external_auth_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    telegram_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, unique=True, index=True
    )
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    integrations: Mapped[list[Integration]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    places: Mapped[list[Place]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

class Integration(TimestampMixin, Base):
    """OAuth-style connection of a user to an external provider (e.g. Yandex, Whoop)."""

    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_integrations_user_provider"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(IntegrationProvider, name="integration_provider", values_callable=_enum_values),
        nullable=False,
    )
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sync_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    user: Mapped[User] = relationship(back_populates="integrations")

class Event(TimestampMixin, Base):
    """Calendar event, possibly mirrored from an external source."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_user_start", "user_id", "start_at"),
        Index("ix_events_user_category", "user_id", "category"),
        UniqueConstraint(
            "user_id", "source", "external_id", name="uq_events_source_external"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source: Mapped[EventSource] = mapped_column(
        Enum(EventSource, name="event_source", values_callable=_enum_values),
        default=EventSource.LOCAL,
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    calendar_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(200), nullable=True)

    is_movable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    user: Mapped[User] = relationship(back_populates="events")

class Task(TimestampMixin, Base):
    """User task that can be auto-scheduled into the calendar."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    earliest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", values_callable=_enum_values),
        default=TaskStatus.PENDING,
        nullable=False,
    )
    scheduled_event_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    focus_required: Mapped[str] = mapped_column(
        String(20), nullable=False, default="shallow"
    )
    splittable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    min_chunk_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(200), nullable=True)
    auto_scheduled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="tasks")

class TaskDependency(Base):
    """Directed edge marking that one task depends on another being done first."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        Index("ix_task_dependencies_depends_on_id", "depends_on_id"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depends_on_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )

class UserPreferences(TimestampMixin, Base):
    """Per-user scheduling preferences (working hours, focus windows, breaks)."""

    __tablename__ = "user_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    working_hours: Mapped[dict] = mapped_column(JSONB, nullable=False)
    focus_windows: Mapped[list] = mapped_column(JSONB, nullable=False)
    min_break_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_continuous_work_minutes: Mapped[int] = mapped_column(
        Integer, default=120, nullable=False
    )
    auto_schedule_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    buffer_after_meeting_minutes: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False
    )

class SchedulingRun(Base):
    """Audit record of one scheduler invocation and its proposed/applied changes."""

    __tablename__ = "scheduling_runs"
    __table_args__ = (
        Index("ix_scheduling_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_changes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class BiometricsSnapshot(TimestampMixin, Base):
    """Daily biometric reading from a wearable provider (e.g. Whoop)."""

    __tablename__ = "biometrics_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "date", "provider", name="uq_biometrics_user_date_provider"),
        Index("ix_biometrics_user_date", "user_id", "date"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(IntegrationProvider, name="integration_provider", values_callable=_enum_values),
        nullable=False,
    )

    recovery_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(nullable=True)
    resting_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_performance: Mapped[float | None] = mapped_column(nullable=True)
    strain: Mapped[float | None] = mapped_column(nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

class DailyBriefing(TimestampMixin, Base):
    """Morning or evening briefing message sent to a user, with optional feedback."""

    __tablename__ = "daily_briefings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "date", "kind", name="uq_daily_briefings_user_date_kind"
        ),
        Index("ix_daily_briefings_user_date", "user_id", "date"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date_cls] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # "morning" | "evening"
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_band: Mapped[str | None] = mapped_column(String(10), nullable=True)  # red/yellow/green
    recovery_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1/2/3
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

class AgentRun(TimestampMixin, Base):
    """Single conversation turn with the assistant agent and its proposal state."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status", values_callable=_enum_values),
        default=AgentRunStatus.RUNNING,
        nullable=False,
    )
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

class CategoryDefinition(TimestampMixin, Base):
    """Per-user category catalog entry (name, color, emoji, optional weekly goal)."""

    __tablename__ = "category_definitions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#9ca3af")
    emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    goal_minutes_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class TelegramLinkToken(Base):
    """Single-use token used to link a Telegram account to an existing user."""

    __tablename__ = "telegram_link_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class Place(TimestampMixin, Base):
    """Named address saved by a user (e.g. home, office) for routing."""

    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_places_user_name"),
        Index("ix_places_user", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="places")

class CategoryCorrection(Base):
    """Recorded user correction of an automatic event category, kept for audit/training."""

    __tablename__ = "category_corrections"
    __table_args__ = (
        Index(
            "ix_category_corrections_user_created", "user_id", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_title: Mapped[str] = mapped_column(String(500), nullable=False)
    event_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    predicted: Mapped[str | None] = mapped_column(String(50), nullable=True)
    predicted_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    predicted_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    corrected: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
