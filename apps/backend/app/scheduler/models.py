"""Dataclass models used as inputs and outputs of the task scheduler."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

FocusKind = Literal["deep", "shallow", "admin"]

@dataclass(slots=True)
class TaskInput:
    """Task to be scheduled, with duration, deadline, focus needs, and dependencies."""

    id: UUID
    title: str
    duration_minutes: int
    priority: int = 5
    deadline_at: datetime | None = None
    earliest_at: datetime | None = None
    focus_required: FocusKind = "shallow"
    splittable: bool = False
    min_chunk_minutes: int = 30
    location: str | None = None
    dependencies: list[UUID] = field(default_factory=list)

@dataclass(slots=True)
class FixedBlock:
    """Immovable busy block (existing event or meeting) that the scheduler must work around."""

    start: datetime
    end: datetime
    title: str = ""
    is_meeting: bool = False

@dataclass(slots=True)
class FocusWindow:
    """Time window suitable for a particular focus kind (deep, shallow, admin)."""

    start: datetime
    end: datetime
    kind: FocusKind

@dataclass(slots=True)
class WorkingWindow:
    """Single contiguous span of working time on one calendar day."""

    start: datetime
    end: datetime

@dataclass(slots=True)
class PreferencesInput:
    """Scheduler-relevant slice of user preferences (breaks, work cap, post-meeting buffer)."""

    min_break_minutes: int = 10
    max_continuous_work_minutes: int = 120
    buffer_after_meeting_minutes: int = 15

@dataclass(slots=True)
class ScheduledChunk:
    """A scheduled time block for a task or one chunk of a splittable task."""

    task_id: UUID
    title: str
    start: datetime
    end: datetime
    focus_required: FocusKind
    chunk_index: int = 0
    chunk_total: int = 1
    score: float = 0.0
    reason: str = ""

@dataclass(slots=True)
class SchedulingResult:
    """Outcome of one scheduling pass: placed chunks, unscheduled tasks, and aggregate score."""
    scheduled: list[ScheduledChunk] = field(default_factory=list)
    unscheduled: list[tuple[UUID, str, str]] = field(default_factory=list)
    total_score: float = 0.0
