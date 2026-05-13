"""Greedy scheduler unit tests — no DB, no LLM."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from app.scheduler.greedy import (
    FixedBlock,
    PlanItem,
    SchedulerInput,
    propose_replan,
)

def _utc(year=2026, month=5, day=7, hour=9, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

def test_empty_inputs_produce_empty_plan():
    out = propose_replan(SchedulerInput(now=_utc()))
    assert out.changes == []
    assert out.unscheduled == []

def test_single_task_fits_in_empty_window():
    item = PlanItem(kind="task", id=uuid4(), title="Deep work", duration_minutes=60, priority=3)
    out = propose_replan(
        SchedulerInput(
            now=_utc(hour=9),
            day_start=time(9, 0),
            day_end=time(18, 0),
            items=[item],
        )
    )
    assert len(out.changes) == 1
    c = out.changes[0]
    assert c.op == "create"
    assert c.new_start is not None and c.new_end is not None
    assert (c.new_end - c.new_start) == timedelta(minutes=60)
    assert out.unscheduled == []

def test_high_priority_placed_first():
    low = PlanItem(kind="task", id=uuid4(), title="Low", duration_minutes=60, priority=1)
    high = PlanItem(kind="task", id=uuid4(), title="High", duration_minutes=60, priority=10)
    out = propose_replan(
        SchedulerInput(
            now=_utc(hour=9),
            day_start=time(9, 0),
            day_end=time(11, 0),
            items=[low, high],
        )
    )
    create_changes = [c for c in out.changes if c.op == "create"]
    assert create_changes[0].item.title == "High"

def test_deadline_excludes_late_slots():
    deadline = _utc(hour=9, minute=30)
    item = PlanItem(
        kind="task",
        id=uuid4(),
        title="Urgent",
        duration_minutes=60,
        priority=5,
        deadline_at=deadline,
    )
    out = propose_replan(
        SchedulerInput(
            now=_utc(hour=9),
            day_start=time(9, 0),
            day_end=time(18, 0),
            items=[item],
        )
    )
    skip = next((c for c in out.changes if c.op == "skip"), None)
    assert skip is not None
    assert skip.item.title == "Urgent"
    assert any(u.title == "Urgent" for u in out.unscheduled)

def test_fixed_blocks_respected():
    fixed = [FixedBlock(start=_utc(hour=10), end=_utc(hour=11), title="Standup")]
    item = PlanItem(kind="task", id=uuid4(), title="Focus", duration_minutes=120, priority=5)
    out = propose_replan(
        SchedulerInput(
            now=_utc(hour=9),
            day_start=time(9, 0),
            day_end=time(18, 0),
            fixed=fixed,
            items=[item],
        )
    )
    create_changes = [c for c in out.changes if c.op == "create"]
    assert len(create_changes) == 1
    placed = create_changes[0]
    assert placed.new_start is not None and placed.new_end is not None
    assert not (placed.new_start < _utc(hour=11) and placed.new_end > _utc(hour=10))

def test_movable_event_preserved_when_already_in_a_good_slot():
    item = PlanItem(
        kind="event",
        id=uuid4(),
        title="Lunch",
        duration_minutes=60,
        priority=2,
        current_start=_utc(hour=13),
        current_end=_utc(hour=14),
    )
    out = propose_replan(
        SchedulerInput(
            now=_utc(hour=9),
            day_start=time(9, 0),
            day_end=time(18, 0),
            fixed=[],
            items=[item],
        )
    )
    moves = [c for c in out.changes if c.op == "move"]
    assert moves == []

def test_movable_event_conflicting_with_new_meeting_gets_moved():
    lunch = PlanItem(
        kind="event",
        id=uuid4(),
        title="Lunch",
        duration_minutes=60,
        priority=2,
        current_start=_utc(hour=13),
        current_end=_utc(hour=14),
    )
    out = propose_replan(
        SchedulerInput(
            now=_utc(hour=9),
            day_start=time(9, 0),
            day_end=time(18, 0),
            fixed=[FixedBlock(start=_utc(hour=12, minute=30), end=_utc(hour=15), title="Surprise")],
            items=[lunch],
        )
    )
    moves = [c for c in out.changes if c.op == "move"]
    assert len(moves) == 1
    new_start = moves[0].new_start
    new_end = moves[0].new_end
    assert new_start is not None and new_end is not None
    assert new_end <= _utc(hour=12, minute=30) or new_start >= _utc(hour=15)
