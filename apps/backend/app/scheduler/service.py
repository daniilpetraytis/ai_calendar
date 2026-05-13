"""High-level scheduler orchestration: load tasks/events, run the planner, persist results."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar import service as cal_service
from app.db.models import (
    SchedulingRun,
    Task,
    TaskDependency,
    TaskStatus,
    User,
    UserPreferences,
)
from app.scheduler.models import (
    FixedBlock,
    PreferencesInput,
    SchedulingResult,
    TaskInput,
)
from app.scheduler.planner import schedule
from app.scheduler.windows import (
    DEFAULT_FOCUS_WINDOWS,
    DEFAULT_WORKING_HOURS,
    compute_focus_windows,
    compute_working_windows,
)

log = logging.getLogger(__name__)

async def get_or_create_preferences(
    session, user
):
    """Return the user's scheduling preferences, creating a default row if missing."""
    existing = await session.get(UserPreferences, user.id)
    if existing is not None:
        return existing
    prefs = UserPreferences(
        user_id=user.id,
        tenant_id=user.tenant_id,
        working_hours=DEFAULT_WORKING_HOURS,
        focus_windows=DEFAULT_FOCUS_WINDOWS,
    )
    session.add(prefs)
    await session.flush()
    return prefs

async def _load_pending_tasks(
    session, user
):
    """Load the user's pending tasks (with dependencies) as ``TaskInput`` instances."""
    rows = (
        await session.execute(
            select(Task).where(
                Task.user_id == user.id, Task.status == TaskStatus.PENDING
            )
        )
    ).scalars().all()
    if not rows:
        return []

    dep_rows = (
        await session.execute(
            select(TaskDependency.task_id, TaskDependency.depends_on_id).where(
                TaskDependency.task_id.in_([r.id for r in rows])
            )
        )
    ).all()
    deps_by_task = {}
    for tid, dep_id in dep_rows:
        deps_by_task.setdefault(tid, []).append(dep_id)

    out = []
    for t in rows:
        out.append(
            TaskInput(
                id=t.id,
                title=t.title,
                duration_minutes=max(5, t.duration_minutes),
                priority=t.priority,
                deadline_at=t.deadline_at,
                earliest_at=t.earliest_at,
                focus_required=t.focus_required if t.focus_required in ("deep", "shallow", "admin") else "shallow",
                splittable=t.splittable,
                min_chunk_minutes=t.min_chunk_minutes or 30,
                location=t.location,
                dependencies=deps_by_task.get(t.id, []),
            )
        )
    return out

async def _load_fixed_blocks(
    session,
    user,
    *,
    start,
    end,
):
    """Load existing non-all-day events in a window as ``FixedBlock`` instances."""
    events = await cal_service.list_events(session, user, start=start, end=end)
    out = []
    for e in events:
        if e.all_day:
            continue
        out.append(
            FixedBlock(
                start=e.start_at,
                end=e.end_at,
                title=e.title,
                is_meeting=(not e.is_movable) or e.source.value != "local",
            )
        )
    return out

def _serialise_chunk(c):
    """Serialise a ``ScheduledChunk`` to the dict shape used by the agent proposal API."""
    return {
        "op": "create",
        "kind": "task",
        "id": str(c.task_id),
        "title": (
            c.title if c.chunk_total <= 1 else f"{c.title} ({c.chunk_index + 1}/{c.chunk_total})"
        ),
        "new_start_iso": c.start.isoformat(),
        "new_end_iso": c.end.isoformat(),
        "reason": c.reason,
    }

def result_to_proposal(
    result, *, summary_prefix = ""
):
    """Convert a ``SchedulingResult`` into the JSON-serialisable proposal shape."""
    placed = len(result.scheduled)
    missed = len(result.unscheduled)
    bits = []
    if placed:
        bits.append(f"{placed} new placement(s)")
    if missed:
        bits.append(f"{missed} could not fit")
    summary = (summary_prefix or "Auto-schedule") + (
        ": " + ", ".join(bits) if bits else ": nothing to do."
    )
    return {
        "summary": summary,
        "changes": [_serialise_chunk(c) for c in result.scheduled],
        "unscheduled": [
            {"id": str(tid), "kind": "task", "title": title, "reason": reason}
            for (tid, title, reason) in result.unscheduled
        ],
    }

async def auto_schedule_user(
    session,
    user,
    *,
    horizon_days = 7,
    apply = False,
    trigger = "manual",
    biometric_factor = 1.0,
):
    """Run the scheduler for a user over the given horizon, audit the run, and optionally apply it."""
    prefs = await get_or_create_preferences(session, user)
    prefs_in = PreferencesInput(
        min_break_minutes=prefs.min_break_minutes,
        max_continuous_work_minutes=prefs.max_continuous_work_minutes,
        buffer_after_meeting_minutes=prefs.buffer_after_meeting_minutes,
    )

    now = datetime.now(UTC)
    horizon_end = now + timedelta(days=max(1, horizon_days))

    tasks = await _load_pending_tasks(session, user)
    fixed = await _load_fixed_blocks(session, user, start=now, end=horizon_end)
    working = compute_working_windows(
        working_hours=prefs.working_hours,
        horizon_start=now,
        horizon_days=horizon_days,
        tz_name=user.timezone,
    )
    focus = compute_focus_windows(
        focus_windows=prefs.focus_windows,
        horizon_start=now,
        horizon_days=horizon_days,
        tz_name=user.timezone,
        working_hours=prefs.working_hours,
    )

    result = schedule(
        tasks=tasks,
        fixed=fixed,
        working=working,
        focus_windows=focus,
        prefs=prefs_in,
        biometric_factor=biometric_factor,
        horizon_origin=now,
    )

    run = SchedulingRun(
        tenant_id=user.tenant_id,
        user_id=user.id,
        trigger=trigger,
        input_snapshot={
            "horizon_days": horizon_days,
            "task_count": len(tasks),
            "fixed_count": len(fixed),
            "working_window_count": len(working),
            "focus_window_count": len(focus),
            "biometric_factor": biometric_factor,
        },
        output_changes=result_to_proposal(result, summary_prefix="Auto-schedule")[
            "changes"
        ],
        applied=apply,
    )
    session.add(run)
    await session.flush()

    if apply:
        await apply_scheduled_chunks(session, user, result)

    return result, run

async def apply_scheduled_chunks(
    session, user, result
):
    """Materialize each scheduled chunk as a calendar event and mark its task as scheduled."""
    applied = 0
    seen_tasks = set()
    for chunk in result.scheduled:
        title = (
            chunk.title
            if chunk.chunk_total <= 1
            else f"{chunk.title} ({chunk.chunk_index + 1}/{chunk.chunk_total})"
        )
        event = await cal_service.create_event(
            session,
            user,
            title=title,
            start=chunk.start,
            end=chunk.end,
        )
        if chunk.task_id not in seen_tasks:
            task = await session.get(Task, chunk.task_id)
            if task is not None and task.user_id == user.id:
                task.status = TaskStatus.SCHEDULED
                task.scheduled_event_id = event.id
                task.auto_scheduled = True
            seen_tasks.add(chunk.task_id)
        applied += 1
    return applied

async def find_slot_for_single(
    session,
    user,
    *,
    duration_minutes,
    deadline_at = None,
    earliest_at = None,
    focus_required = "shallow",
    horizon_days = 7,
    biometric_factor = 1.0,
):
    """Find one ``(start, end)`` slot for a hypothetical task without touching the database."""
    prefs = await get_or_create_preferences(session, user)
    prefs_in = PreferencesInput(
        min_break_minutes=prefs.min_break_minutes,
        max_continuous_work_minutes=prefs.max_continuous_work_minutes,
        buffer_after_meeting_minutes=prefs.buffer_after_meeting_minutes,
    )

    now = datetime.now(UTC)
    horizon_end = now + timedelta(days=max(1, horizon_days))
    fixed = await _load_fixed_blocks(session, user, start=now, end=horizon_end)
    working = compute_working_windows(
        working_hours=prefs.working_hours,
        horizon_start=now,
        horizon_days=horizon_days,
        tz_name=user.timezone,
    )
    focus = compute_focus_windows(
        focus_windows=prefs.focus_windows,
        horizon_start=now,
        horizon_days=horizon_days,
        tz_name=user.timezone,
        working_hours=prefs.working_hours,
    )

    from uuid import uuid4

    probe = TaskInput(
        id=uuid4(),
        title="probe",
        duration_minutes=max(5, duration_minutes),
        priority=5,
        deadline_at=deadline_at,
        earliest_at=earliest_at,
        focus_required=focus_required if focus_required in ("deep", "shallow", "admin") else "shallow",
    )
    result = schedule(
        tasks=[probe],
        fixed=fixed,
        working=working,
        focus_windows=focus,
        prefs=prefs_in,
        biometric_factor=biometric_factor,
        horizon_origin=now,
    )
    if not result.scheduled:
        return None
    chunk = result.scheduled[0]
    return chunk.start, chunk.end
