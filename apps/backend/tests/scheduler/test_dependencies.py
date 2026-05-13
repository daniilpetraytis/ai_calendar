"""Task dependencies: B must start after A finishes."""

from __future__ import annotations

from uuid import uuid4

from app.scheduler.models import TaskInput
from app.scheduler.planner import schedule

from .conftest import single_day_working_window, standard_focus_windows

def test_dependent_task_runs_after_its_dependency():
    a = TaskInput(id=uuid4(), title="A", duration_minutes=60, priority=5)
    b = TaskInput(
        id=uuid4(),
        title="B",
        duration_minutes=60,
        priority=10,  # higher priority but depends on A
        dependencies=[a.id],
    )
    out = schedule(
        tasks=[a, b],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    a_chunk = next(c for c in out.scheduled if c.title == "A")
    b_chunk = next(c for c in out.scheduled if c.title == "B")
    assert b_chunk.start >= a_chunk.end

def test_dependency_cycle_is_skipped_gracefully():
    a_id, b_id = uuid4(), uuid4()
    a = TaskInput(id=a_id, title="A", duration_minutes=60, dependencies=[b_id])
    b = TaskInput(id=b_id, title="B", duration_minutes=60, dependencies=[a_id])
    out = schedule(
        tasks=[a, b],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    assert out.scheduled == []
    titles = {row[1] for row in out.unscheduled}
    assert titles == {"A", "B"}

def test_unscheduled_dependency_blocks_dependent_task():
    deep_focus = standard_focus_windows()
    impossible = TaskInput(
        id=uuid4(),
        title="Impossible",
        duration_minutes=24 * 60,  # cannot fit anywhere
    )
    dependent = TaskInput(
        id=uuid4(),
        title="Dependent",
        duration_minutes=60,
        dependencies=[impossible.id],
    )
    out = schedule(
        tasks=[impossible, dependent],
        fixed=[],
        working=single_day_working_window(),
        focus_windows=deep_focus,
    )
    assert all(c.title != "Dependent" for c in out.scheduled)
    reasons = {title: reason for (_id, title, reason) in out.unscheduled}
    assert "Dependent" in reasons
