"""Pydantic DTOs for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

class EventOut(BaseModel):
    """Calendar event as returned by the API."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    source: Literal["yandex", "local"]
    is_movable: bool
    priority: int
    category: str | None = None
    category_source: str | None = None

class EventCreate(BaseModel):
    """Payload for creating a new local calendar event."""

    title: str
    start_at: datetime
    end_at: datetime
    description: str | None = None
    location: str | None = None
    is_movable: bool = True
    priority: int = 0

class EventUpdate(BaseModel):
    """Partial update payload for an existing event."""

    title: str | None = None
    description: str | None = None
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    category: str | None = None

class CategoryOut(BaseModel):
    """Category definition returned to clients."""

    model_config = ConfigDict(from_attributes=True)
    name: str
    color: str
    emoji: str | None = None
    goal_minutes_per_week: int | None = None
    is_default: bool

class CategoryCreate(BaseModel):
    """Payload for creating a new user-defined category."""

    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field(default="#9ca3af", pattern=r"^#[0-9a-fA-F]{6}$")
    emoji: str | None = None
    goal_minutes_per_week: int | None = Field(default=None, ge=1)

class CategoryUpdate(BaseModel):
    """Partial update payload for an existing category."""

    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    emoji: str | None = None
    goal_minutes_per_week: int | None = Field(default=None, ge=1)

class CategoryStatItem(BaseModel):
    """Aggregated minutes for one category over a stats period."""

    category: str
    minutes: int
    color: str
    emoji: str | None = None
    goal_minutes_per_week: int | None = None

class DayCategoryItem(BaseModel):
    """Per-category minutes inside a single day."""

    category: str
    minutes: int
    color: str
    emoji: str | None = None

class DayStatItem(BaseModel):
    """Daily totals broken down by category."""

    date: str        # ISO date "2026-05-06"
    day_label: str   # "Mon"
    total_minutes: int
    by_category: list[DayCategoryItem]

class StatsByCategoryOut(BaseModel):
    """Time-by-category breakdown for a single stats period."""

    period_label: str
    period_start: datetime
    period_end: datetime
    total_minutes: int
    by_category: list[CategoryStatItem]

class HeatmapCell(BaseModel):
    """One cell of the day-of-week × hour-of-day heatmap."""

    day: int   # 0=Monday … 6=Sunday
    hour: int  # 0–23
    minutes: int

class HeatmapOut(BaseModel):
    """Heatmap of busy minutes across day-of-week and hour-of-day."""

    period_label: str
    cells: list[HeatmapCell]

class TrendItem(BaseModel):
    """Per-category change between the current and previous period."""

    category: str
    color: str
    emoji: str | None = None
    current_minutes: int
    previous_minutes: int
    delta_minutes: int
    delta_pct: float | None = None  # None when previous == 0

class TrendsOut(BaseModel):
    """Period-over-period trend response across all categories."""

    period_label: str
    previous_label: str
    items: list[TrendItem]

FocusKindLiteral = Literal["deep", "shallow", "admin"]

class TaskOut(BaseModel):
    """Task representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str | None
    duration_minutes: int
    priority: int
    deadline_at: datetime | None
    earliest_at: datetime | None
    status: Literal["pending", "scheduled", "done", "skipped"]
    scheduled_event_id: UUID | None
    tags: list[str]
    focus_required: FocusKindLiteral = "shallow"
    splittable: bool = False
    min_chunk_minutes: int = 30
    recurrence_rule: str | None = None
    auto_scheduled: bool = False
    location: str | None = None
    category: str | None = None
    estimated_minutes: int | None = None
    completed_at: datetime | None = None
    dependencies: list[UUID] = Field(default_factory=list)

class TaskCreate(BaseModel):
    """Payload for creating a new task."""

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    duration_minutes: int = Field(default=30, ge=5)
    priority: int = Field(default=5, ge=0, le=10)
    deadline_at: datetime | None = None
    earliest_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    focus_required: FocusKindLiteral = "shallow"
    splittable: bool = False
    min_chunk_minutes: int = Field(default=30, ge=5)
    recurrence_rule: str | None = None
    location: str | None = None
    category: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=5)
    auto_schedule: bool = False
    dependencies: list[UUID] = Field(default_factory=list)

class TaskUpdate(BaseModel):
    """Partial update payload for an existing task."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5)
    priority: int | None = Field(default=None, ge=0, le=10)
    deadline_at: datetime | None = None
    earliest_at: datetime | None = None
    tags: list[str] | None = None
    focus_required: FocusKindLiteral | None = None
    splittable: bool | None = None
    min_chunk_minutes: int | None = Field(default=None, ge=5)
    recurrence_rule: str | None = None
    location: str | None = None
    category: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=5)
    status: Literal["pending", "scheduled", "done", "skipped"] | None = None
    dependencies: list[UUID] | None = None

class TaskComplete(BaseModel):
    """Payload for marking a task as complete."""

    actual_duration_minutes: int | None = Field(default=None, ge=1)

class TaskDefer(BaseModel):
    """Payload for deferring a task to a later time."""

    to_at: datetime | None = None  # if null → next available slot
    reason: str | None = None

class TaskScheduleRequest(BaseModel):
    """Payload for scheduling a task at an explicit time or via auto-find."""

    at: datetime | None = None  # if null → auto find slot

class WorkingHoursEntry(BaseModel):
    """A single day's working hours window."""

    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$")

class FocusWindowEntry(BaseModel):
    """A daily focus window with an associated focus kind."""

    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    kind: FocusKindLiteral = "shallow"

class PreferencesOut(BaseModel):
    """User scheduling preferences returned by the API."""

    model_config = ConfigDict(from_attributes=True)
    working_hours: dict[str, WorkingHoursEntry | None]
    focus_windows: list[FocusWindowEntry]
    min_break_minutes: int
    max_continuous_work_minutes: int
    auto_schedule_enabled: bool
    buffer_after_meeting_minutes: int

class PreferencesUpdate(BaseModel):
    """Partial update payload for scheduling preferences."""

    working_hours: dict[str, WorkingHoursEntry | None] | None = None
    focus_windows: list[FocusWindowEntry] | None = None
    min_break_minutes: int | None = Field(default=None, ge=0, le=120)
    max_continuous_work_minutes: int | None = Field(default=None, ge=30, le=600)
    auto_schedule_enabled: bool | None = None
    buffer_after_meeting_minutes: int | None = Field(default=None, ge=0, le=120)

class SchedulerRunRequest(BaseModel):
    """Request body for running the auto-scheduler."""

    horizon_days: int = Field(default=7, ge=1, le=30)
    apply: bool = False
    biometric_factor: float = Field(default=1.0, ge=0.0, le=1.0)

class SchedulerChange(BaseModel):
    """A single create/move action proposed by the scheduler."""

    op: Literal["create", "move"]
    kind: Literal["task"] = "task"
    id: str
    title: str
    new_start_iso: str
    new_end_iso: str
    reason: str | None = None

class SchedulerUnscheduled(BaseModel):
    """A task the scheduler could not place, with a human-readable reason."""

    id: str
    kind: Literal["task"] = "task"
    title: str
    reason: str

class SchedulerProposalOut(BaseModel):
    """Full proposal produced by the scheduler for a single run."""

    summary: str
    changes: list[SchedulerChange]
    unscheduled: list[SchedulerUnscheduled] = Field(default_factory=list)

class SchedulerRunResponse(BaseModel):
    """Response from a scheduler run, including any applied changes."""

    proposal: SchedulerProposalOut
    applied_count: int = 0
    run_id: UUID
    horizon_days: int

class ChatMessage(BaseModel):
    """Inbound chat message from the user, with optional thread id."""

    message: str
    thread_id: str | None = None

class YandexConnectRequest(BaseModel):
    """Credentials for connecting a Yandex CalDAV account."""

    email: str = Field(..., examples=["alice@yandex.ru"])
    app_password: str = Field(..., min_length=8)

class ProposedChange(BaseModel):
    """One change proposed by the replanning agent for user review."""

    op: Literal["create", "move", "update", "delete"]
    event_id: UUID | None = None
    title: str | None = None
    new_start_at: datetime | None = None
    new_end_at: datetime | None = None
    description: str | None = None
    location: str | None = None
    reason: str | None = None

class ReplanProposal(BaseModel):
    """Replan proposal returned to the client for approval."""

    summary: str
    changes: list[ProposedChange]

class ReplanDecision(BaseModel):
    """User's decision on a replan proposal."""

    approve: bool
    accepted_indices: list[int] | None = None  # if None and approve=True -> approve all

class PlaceOut(BaseModel):
    """A saved place returned to the client."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    address: str
    is_default: bool

class PlaceCreate(BaseModel):
    """Payload for creating a new saved place."""

    name: str = Field(..., min_length=1, max_length=80)
    address: str = Field(..., min_length=1, max_length=500)
    is_default: bool = False

class PlaceUpdate(BaseModel):
    """Partial update payload for a saved place."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    is_default: bool | None = None

class BiometricsToday(BaseModel):
    """Today's biometric snapshot derived from the latest Whoop sync."""

    available: bool
    date: str | None = None  # ISO local date, "2026-05-12"
    recovery_score: int | None = None
    recovery_band: Literal["red", "yellow", "green"] | None = None
    hrv_rmssd_ms: float | None = None
    resting_heart_rate: int | None = None
    sleep_performance: float | None = None
    sleep_hours: float | None = None
    strain: float | None = None
    last_synced_at: datetime | None = None

class BiometricsHistoryItem(BaseModel):
    """One day of biometric history."""

    date: str  # ISO local date
    recovery_score: int | None = None
    recovery_band: Literal["red", "yellow", "green"] | None = None
    strain: float | None = None
    sleep_hours: float | None = None

class EveningFeedbackIn(BaseModel):
    """User's subjective evening feedback for the daily briefing."""

    score: int = Field(..., ge=1, le=3)  # 1=легко, 2=ок, 3=тяжко
    text: str | None = Field(default=None, max_length=500)

class InsightOut(BaseModel):
    """A single derived insight with a short title and longer detail."""

    title: str
    detail: str
