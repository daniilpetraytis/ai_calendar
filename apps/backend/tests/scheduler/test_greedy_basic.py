"""Sanity tests: simple inputs, sensible outputs."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.scheduler.models import TaskInput
from app.scheduler.planner import schedule

from .conftest import single_day_working_window, standard_focus_windows

def test_empty_tasks_returns_empty_result():
    out = schedule(
        tasks=[],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert out.scheduled == []
    assert out.unscheduled == []

def test_single_task_fits_in_empty_window():
    task = TaskInput(
        id=uuid4(),
        title="Deep work",
        duration_minutes=60,
        focus_required="deep",
    )
    out = schedule(
        tasks=[task],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert len(out.scheduled) == 1
    chunk = out.scheduled[0]
    assert (chunk.end - chunk.start) == timedelta(minutes=60)
    assert out.unscheduled == []

def test_higher_priority_goes_to_higher_score_slot():
    low = TaskInput(id=uuid4(), title="Low", duration_minutes=60, priority=1, focus_required="deep")
    high = TaskInput(id=uuid4(), title="High", duration_minutes=60, priority=10, focus_required="deep")
    out = schedule(
        tasks=[low, high],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert len(out.scheduled) == 2
    titles_ordered_by_start = [
        c.title for c in sorted(out.scheduled, key=lambda c: c.start)
    ]
    assert titles_ordered_by_start[0] == "High"
