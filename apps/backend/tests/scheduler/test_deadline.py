"""Deadlines: task lands before deadline or surfaces as unscheduled."""

from __future__ import annotations

from uuid import uuid4

from app.scheduler.models import TaskInput
from app.scheduler.planner import schedule

from .conftest import single_day_working_window, standard_focus_windows, utc

def test_task_lands_before_hard_deadline():
    deadline = utc(hour=12)
    task = TaskInput(
        id=uuid4(),
        title="Report",
        duration_minutes=60,
        deadline_at=deadline,
        focus_required="deep",
    )
    out = schedule(
        tasks=[task],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert len(out.scheduled) == 1
    assert out.scheduled[0].end <= deadline

def test_unreachable_deadline_surfaces_in_unscheduled():
    deadline = utc(hour=9, minute=30)
    task = TaskInput(
        id=uuid4(),
        title="Impossible",
        duration_minutes=120,
        deadline_at=deadline,
    )
    out = schedule(
        tasks=[task],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert out.scheduled == []
    assert any(t[1] == "Impossible" for t in out.unscheduled)

def test_deadline_pressure_beats_priority_for_ordering():
    deadlined = TaskInput(
        id=uuid4(),
        title="Deadlined",
        duration_minutes=60,
        priority=1,
        deadline_at=utc(hour=12),
    )
    high_prio = TaskInput(
        id=uuid4(),
        title="HighPri",
        duration_minutes=60,
        priority=10,
    )
    out = schedule(
        tasks=[deadlined, high_prio],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    by_start = sorted(out.scheduled, key=lambda c: c.start)
    assert by_start[0].title == "Deadlined"
