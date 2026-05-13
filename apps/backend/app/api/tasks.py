"""Task CRUD, completion, deferral and scheduling endpoints."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.api.schemas import (
    TaskComplete,
    TaskCreate,
    TaskDefer,
    TaskOut,
    TaskScheduleRequest,
    TaskUpdate,
)
from app.calendar import service as cal_service
from app.db.models import Task, TaskDependency, TaskStatus
from app.deps import CurrentUser, DbSession
from app.scheduler.service import find_slot_for_single

router = APIRouter()

async def _load_dependencies(session, task_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    """Load dependency edges keyed by task id for the supplied task ids."""
    if not task_ids:
        return {}
    rows = (
        await session.execute(
            select(TaskDependency.task_id, TaskDependency.depends_on_id).where(
                TaskDependency.task_id.in_(task_ids)
            )
        )
    ).all()
    out: dict[UUID, list[UUID]] = {}
    for tid, dep in rows:
        out.setdefault(tid, []).append(dep)
    return out

def _serialise_task(task: Task, deps: list[UUID]) -> dict:
    """Convert a Task ORM row plus its dependency ids into the API dict."""
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "duration_minutes": task.duration_minutes,
        "priority": task.priority,
        "deadline_at": task.deadline_at,
        "earliest_at": task.earliest_at,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "scheduled_event_id": task.scheduled_event_id,
        "tags": task.tags or [],
        "focus_required": task.focus_required,
        "splittable": task.splittable,
        "min_chunk_minutes": task.min_chunk_minutes,
        "recurrence_rule": task.recurrence_rule,
        "auto_scheduled": task.auto_scheduled,
        "location": task.location,
        "category": task.category,
        "estimated_minutes": task.estimated_minutes,
        "completed_at": task.completed_at,
        "dependencies": deps,
    }

async def _set_dependencies(session, task: Task, deps: list[UUID]) -> None:
    """Replace the task's dependency edges, validating ownership of each target."""
    deps = [d for d in deps if d != task.id]
    if deps:
        rows = (
            await session.execute(
                select(Task.id).where(
                    Task.id.in_(deps), Task.user_id == task.user_id
                )
            )
        ).scalars().all()
        if len(set(rows)) != len(set(deps)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "One or more dependencies do not exist or belong to a different user.",
            )
    await session.execute(
        delete(TaskDependency).where(TaskDependency.task_id == task.id)
    )
    for dep in set(deps):
        session.add(TaskDependency(task_id=task.id, depends_on_id=dep))

async def _get_owned_task(session, user, task_id: UUID) -> Task:
    """Fetch a task owned by the current user or raise 404."""
    task = await session.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task

@router.get("", response_model=list[TaskOut])
async def list_tasks(
    user: CurrentUser,
    session: DbSession,
    status_filter: str | None = None,
):
    """List the user's tasks, optionally filtered by status."""
    stmt = select(Task).where(Task.user_id == user.id)
    if status_filter:
        try:
            stmt = stmt.where(Task.status == TaskStatus(status_filter))
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown status '{status_filter}'.",
            ) from exc
    rows = (
        await session.execute(stmt.order_by(Task.created_at.desc()))
    ).scalars().all()
    deps_map = await _load_dependencies(session, [t.id for t in rows])
    return [_serialise_task(t, deps_map.get(t.id, [])) for t in rows]

@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate, user: CurrentUser, session: DbSession
) -> TaskOut:
    """Create a new task and optionally auto-schedule it."""
    task = Task(
        tenant_id=user.tenant_id,
        user_id=user.id,
        title=body.title,
        description=body.description,
        duration_minutes=body.duration_minutes,
        priority=body.priority,
        deadline_at=body.deadline_at,
        earliest_at=body.earliest_at,
        tags=body.tags,
        focus_required=body.focus_required,
        splittable=body.splittable,
        min_chunk_minutes=body.min_chunk_minutes,
        recurrence_rule=body.recurrence_rule,
        location=body.location,
        category=body.category,
        estimated_minutes=body.estimated_minutes or body.duration_minutes,
    )
    session.add(task)
    await session.flush()
    if body.dependencies:
        await _set_dependencies(session, task, body.dependencies)
        await session.flush()
    deps = (await _load_dependencies(session, [task.id])).get(task.id, [])

    if body.auto_schedule:
        slot = await find_slot_for_single(
            session,
            user,
            duration_minutes=task.duration_minutes,
            deadline_at=task.deadline_at,
            earliest_at=task.earliest_at,
            focus_required=task.focus_required,
        )
        if slot is not None:
            await _materialise_task(
                session, user, task, slot[0], slot[1], auto_scheduled=True
            )

    return _serialise_task(task, deps)  # type: ignore[return-value]

@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: UUID, body: TaskUpdate, user: CurrentUser, session: DbSession
) -> TaskOut:
    """Patch fields, status and dependencies of an existing task."""
    task = await _get_owned_task(session, user, task_id)
    data = body.model_dump(exclude_unset=True)
    deps = data.pop("dependencies", None)
    status_str = data.pop("status", None)
    for field, value in data.items():
        setattr(task, field, value)
    if status_str is not None:
        task.status = TaskStatus(status_str)
    if deps is not None:
        await _set_dependencies(session, task, deps)
    await session.flush()
    deps_map = await _load_dependencies(session, [task.id])
    return _serialise_task(task, deps_map.get(task.id, []))  # type: ignore[return-value]

@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: UUID, user: CurrentUser, session: DbSession) -> None:
    """Delete one of the user's tasks."""
    task = await _get_owned_task(session, user, task_id)
    await session.delete(task)

@router.post("/{task_id}/complete", response_model=TaskOut)
async def complete_task(
    task_id: UUID,
    body: TaskComplete,
    user: CurrentUser,
    session: DbSession,
) -> TaskOut:
    """Mark a task as done and record its actual duration if provided."""
    task = await _get_owned_task(session, user, task_id)
    task.status = TaskStatus.DONE
    task.completed_at = datetime.now(UTC)
    if body.actual_duration_minutes is not None:
        # Keep the LLM estimate for learning; update actual.
        if task.estimated_minutes is None:
            task.estimated_minutes = task.duration_minutes
        task.duration_minutes = body.actual_duration_minutes
    await session.flush()
    deps_map = await _load_dependencies(session, [task.id])
    return _serialise_task(task, deps_map.get(task.id, []))  # type: ignore[return-value]

@router.post("/{task_id}/defer", response_model=TaskOut)
async def defer_task(
    task_id: UUID,
    body: TaskDefer,
    user: CurrentUser,
    session: DbSession,
) -> TaskOut:
    """Unschedule a task and optionally postpone its earliest start."""
    task = await _get_owned_task(session, user, task_id)
    if task.scheduled_event_id is not None:
        # Don't fail the defer if the event was already gone.
        with contextlib.suppress(Exception):
            await cal_service.delete_event(
                session, user, event_id=task.scheduled_event_id
            )
        task.scheduled_event_id = None
    task.status = TaskStatus.PENDING
    task.auto_scheduled = False
    if body.to_at is not None:
        task.earliest_at = body.to_at
    await session.flush()
    deps_map = await _load_dependencies(session, [task.id])
    return _serialise_task(task, deps_map.get(task.id, []))  # type: ignore[return-value]

@router.post("/{task_id}/schedule", response_model=TaskOut)
async def schedule_task(
    task_id: UUID,
    body: TaskScheduleRequest,
    user: CurrentUser,
    session: DbSession,
) -> TaskOut:
    """Schedule a pending task at an explicit time or via auto slot finding."""
    task = await _get_owned_task(session, user, task_id)
    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Task is in status '{task.status.value}', not pending.",
        )

    if body.at is not None:
        start = body.at
        end = start + _duration(task.duration_minutes)
        await _materialise_task(
            session, user, task, start, end, auto_scheduled=False
        )
    else:
        slot = await find_slot_for_single(
            session,
            user,
            duration_minutes=task.duration_minutes,
            deadline_at=task.deadline_at,
            earliest_at=task.earliest_at,
            focus_required=task.focus_required,
        )
        if slot is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "No available slot before the task's deadline.",
            )
        start, end = slot
        await _materialise_task(
            session, user, task, start, end, auto_scheduled=True
        )

    deps_map = await _load_dependencies(session, [task.id])
    return _serialise_task(task, deps_map.get(task.id, []))  # type: ignore[return-value]

def _duration(minutes: int):
    """Return a timedelta clamped to at least 5 minutes."""
    from datetime import timedelta

    return timedelta(minutes=max(5, minutes))

async def _materialise_task(
    session,
    user,
    task: Task,
    start: datetime,
    end: datetime,
    *,
    auto_scheduled: bool,
) -> None:
    """Create the calendar event backing a scheduled task and link them."""
    event = await cal_service.create_event(
        session,
        user,
        title=task.title,
        start=start,
        end=end,
        description=task.description,
        location=task.location,
    )
    task.scheduled_event_id = event.id
    task.status = TaskStatus.SCHEDULED
    task.auto_scheduled = auto_scheduled
