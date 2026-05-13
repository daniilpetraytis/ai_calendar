"""Focus matching: deep work in morning windows, shallow in afternoon."""

from __future__ import annotations

from uuid import uuid4

from app.scheduler.models import TaskInput
from app.scheduler.planner import schedule

from .conftest import single_day_working_window, standard_focus_windows

def test_deep_task_prefers_deep_window():
    deep = TaskInput(
        id=uuid4(),
        title="Refactor",
        duration_minutes=60,
        focus_required="deep",
    )
    out = schedule(
        tasks=[deep],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert len(out.scheduled) == 1
    chunk = out.scheduled[0]
    assert 9 <= chunk.start.hour < 12

def test_shallow_task_prefers_shallow_window():
    shallow = TaskInput(
        id=uuid4(),
        title="Inbox",
        duration_minutes=60,
        focus_required="shallow",
    )
    out = schedule(
        tasks=[shallow],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert len(out.scheduled) == 1
    chunk = out.scheduled[0]
    assert 14 <= chunk.start.hour < 17

def test_low_recovery_pushes_deep_off_today_if_other_tasks_compete():
    deep = TaskInput(
        id=uuid4(),
        title="Deep",
        duration_minutes=60,
        focus_required="deep",
        priority=5,
    )
    shallow = TaskInput(
        id=uuid4(),
        title="Shallow",
        duration_minutes=60,
        focus_required="shallow",
        priority=5,
    )
    out = schedule(
        tasks=[deep, shallow],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
        biometric_factor=0.3,
    )
    assert len(out.scheduled) == 2
    deep_chunk = next(c for c in out.scheduled if c.title == "Deep")
    assert deep_chunk.score < 80
