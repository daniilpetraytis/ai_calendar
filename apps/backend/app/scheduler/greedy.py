"""Simple greedy task replanner — first-fit placement into working-hour gaps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

@dataclass(slots=True)
class PlanItem:
    """An event or task considered for placement by the greedy planner."""

    kind: str  # "event" | "task"
    id: UUID
    title: str
    duration_minutes: int
    priority: int = 0
    earliest_at: datetime | None = None
    deadline_at: datetime | None = None
    current_start: datetime | None = None
    current_end: datetime | None = None

@dataclass(slots=True)
class FixedBlock:
    """Immovable busy block on the calendar that the planner must respect."""
    start: datetime
    end: datetime
    title: str = ""

@dataclass(slots=True)
class SchedulerInput:
    """Inputs to one greedy planning run: clock, day window, fixed blocks, and items to place."""
    now: datetime
    day_start: time = time(9, 0)
    day_end: time = time(20, 0)
    horizon_days: int = 1
    fixed: list[FixedBlock] = field(default_factory=list)
    items: list[PlanItem] = field(default_factory=list)

@dataclass(slots=True)
class ScheduledChange:
    """A single proposed change for an item: move, create, or skip."""
    op: str  # "move" | "create" | "skip"
    item: PlanItem
    new_start: datetime | None = None
    new_end: datetime | None = None
    reason: str = ""

@dataclass(slots=True)
class SchedulerProposal:
    """Result of one planning run: human-readable summary, proposed changes, and unplaced items."""
    summary: str
    changes: list[ScheduledChange]
    unscheduled: list[PlanItem]

def _free_intervals(
    window_start, window_end, fixed
):
    """Return the gaps in ``[window_start, window_end]`` not covered by any fixed block."""
    blocks = sorted(
        ((max(b.start, window_start), min(b.end, window_end)) for b in fixed),
        key=lambda x: x[0],
    )
    blocks = [b for b in blocks if b[0] < b[1]]
    out = []
    cursor = window_start
    for s, e in blocks:
        if s > cursor:
            out.append((cursor, s))
        if e > cursor:
            cursor = e
    if cursor < window_end:
        out.append((cursor, window_end))
    return [iv for iv in out if iv[1] - iv[0] >= timedelta(minutes=5)]

def _split_into_day_windows(inp):
    """Expand the planning horizon into per-day working-hour windows."""
    out = []
    base = inp.now
    for d in range(inp.horizon_days):
        day = (base + timedelta(days=d)).date()
        start = datetime.combine(day, inp.day_start, tzinfo=UTC)
        end = datetime.combine(day, inp.day_end, tzinfo=UTC)
        if d == 0 and inp.now > start:
            start = inp.now
        if start < end:
            out.append((start, end))
    return out

def _sort_key(item):
    """Sort key prioritizing higher priority, earlier deadline, then longer duration."""
    deadline_score = item.deadline_at.timestamp() if item.deadline_at else 1e15
    return (-item.priority, deadline_score, -item.duration_minutes)

def _overlaps(a_start, a_end, b_start, b_end):
    """Return whether two half-open intervals overlap."""
    return a_start < b_end and b_start < a_end

def _consume_interval(
    free,
    block_start,
    block_end,
):
    """Subtract ``[block_start, block_end]`` from a list of free intervals."""
    out = []
    for s, e in free:
        if e <= block_start or s >= block_end:
            out.append((s, e))
            continue
        if s < block_start:
            out.append((s, block_start))
        if e > block_end:
            out.append((block_end, e))
    return [iv for iv in out if iv[1] - iv[0] >= timedelta(minutes=5)]

def propose_replan(inp):
    """Greedily place items into free working-hour gaps and return a proposal of changes."""
    if not inp.items:
        return SchedulerProposal(summary="Nothing to plan.", changes=[], unscheduled=[])

    windows = _split_into_day_windows(inp)
    free = []
    for ws, we in windows:
        free.extend(_free_intervals(ws, we, inp.fixed))

    items_to_place = []
    for item in inp.items:
        if item.kind == "event" and item.current_start and item.current_end:
            conflicts = any(
                _overlaps(item.current_start, item.current_end, fb.start, fb.end)
                for fb in inp.fixed
            )
            if not conflicts:
                free = _consume_interval(free, item.current_start, item.current_end)
                continue
        items_to_place.append(item)

    items_to_place.sort(key=_sort_key)
    changes = []
    unscheduled = []

    for item in items_to_place:
        duration = timedelta(minutes=max(item.duration_minutes, 5))
        placed = False
        for idx, (s, e) in enumerate(free):
            slot_start = s
            if item.earliest_at and item.earliest_at > slot_start:
                slot_start = item.earliest_at
            if item.deadline_at and slot_start + duration > item.deadline_at:
                continue
            if slot_start + duration <= e:
                new_start, new_end = slot_start, slot_start + duration
                op = "create" if item.kind == "task" else "move"
                changes.append(
                    ScheduledChange(
                        op=op,
                        item=item,
                        new_start=new_start,
                        new_end=new_end,
                        reason=_explain(item, new_start),
                    )
                )
                free[idx] = (new_end, e)
                placed = True
                break
        if not placed:
            unscheduled.append(item)
            changes.append(
                ScheduledChange(op="skip", item=item, reason="no free slot before deadline")
            )

    summary = _build_summary(changes, unscheduled)
    return SchedulerProposal(summary=summary, changes=changes, unscheduled=unscheduled)

def _explain(item, new_start):
    """Build a short reason string explaining why an item was placed at ``new_start``."""
    bits = []
    if item.priority > 0:
        bits.append(f"priority {item.priority}")
    if item.deadline_at:
        bits.append(f"deadline {item.deadline_at.isoformat()}")
    bits.append(f"placed at {new_start.strftime('%H:%M')}")
    return ", ".join(bits)

def _build_summary(changes, unscheduled):
    """Produce a one-line human-readable summary of a planner result."""
    moved = sum(1 for c in changes if c.op == "move")
    created = sum(1 for c in changes if c.op == "create")
    return (
        f"Proposed {moved} move(s) and {created} new placement(s). "
        f"{len(unscheduled)} item(s) could not fit before their deadlines."
    )

def make_dummy_id():
    """Return a fresh UUID for ad-hoc plan items that have no persistent identity."""
    return uuid4()
