"""Splittable tasks: scheduler can break them into ≥min_chunk_minutes pieces."""

from __future__ import annotations

from uuid import uuid4

from app.scheduler.models import FixedBlock, TaskInput
from app.scheduler.planner import schedule

from .conftest import single_day_working_window, standard_focus_windows, utc

def test_splittable_task_fills_around_meetings():
    meetings = [
        FixedBlock(start=utc(hour=10), end=utc(hour=11)),
        FixedBlock(start=utc(hour=13), end=utc(hour=15)),
    ]
    task = TaskInput(
        id=uuid4(),
        title="Project",
        duration_minutes=240,
        splittable=True,
        min_chunk_minutes=30,
        focus_required="shallow",
    )
    out = schedule(
        tasks=[task],
        fixed=meetings,
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
    )
    total = sum(
        int((c.end - c.start).total_seconds() // 60) for c in out.scheduled
    )
    assert total == 240
    assert len(out.scheduled) >= 2
    assert all(c.chunk_total == len(out.scheduled) for c in out.scheduled)

def test_non_splittable_task_into_fragmented_day_stays_unscheduled():
    meetings = [
        FixedBlock(start=utc(hour=10), end=utc(hour=11, minute=15)),
        FixedBlock(start=utc(hour=12, minute=15), end=utc(hour=13, minute=15)),
        FixedBlock(start=utc(hour=14, minute=15), end=utc(hour=15, minute=15)),
        FixedBlock(start=utc(hour=16, minute=15), end=utc(hour=17, minute=15)),
    ]
    task = TaskInput(
        id=uuid4(),
        title="Big block",
        duration_minutes=90,
        splittable=False,
    )
    out = schedule(
        tasks=[task],
        fixed=meetings,
        working=single_day_working_window(start_hour=9, end_hour=18),
        focus_windows=standard_focus_windows(),
    )
    assert out.scheduled == []
    assert any(row[1] == "Big block" for row in out.unscheduled)
