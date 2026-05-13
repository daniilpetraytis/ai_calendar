"""Overflow: too many tasks for one working day → some unscheduled."""

from __future__ import annotations

from uuid import uuid4

from app.scheduler.models import TaskInput
from app.scheduler.planner import schedule

from .conftest import single_day_working_window, standard_focus_windows

def test_unfittable_tasks_listed_as_unscheduled():
    tasks = [
        TaskInput(
            id=uuid4(),
            title=f"T{i}",
            duration_minutes=60,
            focus_required="shallow",
            priority=i,
        )
        for i in range(10)
    ]
    out = schedule(
        tasks=tasks,
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert len(out.unscheduled) >= 1
    assert len(out.scheduled) + len(out.unscheduled) == 10

def test_oversize_task_returns_unscheduled():
    task = TaskInput(
        id=uuid4(),
        title="Marathon",
        duration_minutes=12 * 60,
    )
    out = schedule(
        tasks=[task],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert out.scheduled == []
    assert len(out.unscheduled) == 1
