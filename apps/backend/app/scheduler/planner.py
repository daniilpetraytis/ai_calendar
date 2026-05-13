"""Focus-aware greedy task planner (Phase G).

A deterministic best-slot-fit scheduler that goes a few steps beyond the
original ``app.scheduler.greedy.propose_replan``:

* sorts by hard-deadline first, then priority — never letting a low-priority
  but soon-to-expire task get starved;
* scores candidate slots against the user's focus windows (deep work in the
  morning, shallow afternoon) and a biometric factor (low recovery → demote
  deep work today);
* respects task dependencies (A → B means B must finish before A starts);
* honours splittable / min_chunk_minutes (a 4h task with 30m chunks may be
  spread across 8 thirty-minute holes);
* honours min_break_minutes between consecutive task chunks;
* respects buffer_after_meeting_minutes after fixed *meeting* blocks.

It is intentionally pure Python — no DB, no LLM. The service layer
(:mod:`app.scheduler.service`) is responsible for loading inputs from the DB,
calling :func:`schedule`, and writing the result back.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from uuid import UUID

from app.scheduler.models import (
    FixedBlock,
    FocusKind,
    FocusWindow,
    PreferencesInput,
    ScheduledChunk,
    SchedulingResult,
    TaskInput,
    WorkingWindow,
)

log = logging.getLogger(__name__)


_GRID_MINUTES = 15
_MIN_SLOT_MINUTES = 5

# Score weights — keep these on a single page so they're easy to tune.
_W_FOCUS_MATCH = 50.0
_W_FOCUS_MISMATCH = -10.0
_W_BUFFER_HONOURED = 10.0
# Earlier placement is preferred unless the user explicitly requested a
# late start via ``earliest_at``. We multiply this by the number of FULL
# days between ``now`` and the candidate slot, so the further out the slot
# the more it costs. Combined with the per-second tiebreaker this gives a
# stable "do it sooner" ordering without overpowering focus match.
_W_PER_DAY_DELAY = -1.0
_W_EARLY_DAY = 2.0
_W_OVER_CONTINUOUS_LIMIT = -30.0
_W_BIOMETRIC_LOW = -20.0


def _free_intervals(
    windows: list[WorkingWindow], fixed: list[FixedBlock]
) -> list[tuple[datetime, datetime, bool]]:
    """Subtract ``fixed`` from ``windows``.

    Returns a list of ``(start, end, is_after_meeting)`` triples where the
    third element marks whether the interval starts right after a meeting
    block (for buffer-bonus scoring).
    """
    sorted_fixed = sorted(fixed, key=lambda b: b.start)
    out: list[tuple[datetime, datetime, bool]] = []
    for win in windows:
        cursor = win.start
        after_meeting = False
        for fb in sorted_fixed:
            if fb.end <= cursor or fb.start >= win.end:
                continue
            fb_s = max(fb.start, win.start)
            fb_e = min(fb.end, win.end)
            if fb_s > cursor:
                out.append((cursor, fb_s, after_meeting))
            cursor = max(cursor, fb_e)
            after_meeting = fb.is_meeting
        if cursor < win.end:
            out.append((cursor, win.end, after_meeting))
    return [
        (s, e, am)
        for (s, e, am) in out
        if (e - s) >= timedelta(minutes=_MIN_SLOT_MINUTES)
    ]


def _topo_order_tasks(
    tasks: list[TaskInput],
) -> tuple[list[TaskInput], set[UUID]]:
    """Return tasks in dependency-aware order.

    Tasks involved in a cycle (or that depend on something we didn't get) end
    up in the trailing portion of the order with their ids returned in the
    second tuple element — the caller drops them as unschedulable.
    """
    by_id = {t.id: t for t in tasks}
    in_degree: dict[UUID, int] = {t.id: 0 for t in tasks}
    for t in tasks:
        for dep in t.dependencies:
            if dep in by_id:
                in_degree[t.id] += 1
    # Kahn's algorithm with deterministic ordering for ties.
    ready: deque[UUID] = deque(
        sorted(
            (tid for tid, deg in in_degree.items() if deg == 0),
            key=lambda tid: _sort_key(by_id[tid]),
        )
    )
    ordered: list[TaskInput] = []
    while ready:
        cur = ready.popleft()
        ordered.append(by_id[cur])
        for t in tasks:
            if cur in t.dependencies:
                in_degree[t.id] -= 1
                if in_degree[t.id] == 0:
                    ready.append(t.id)
    cycled = {t.id for t in tasks if t.id not in {o.id for o in ordered}}
    if cycled:
        log.warning("Task dependency cycle detected: %s", cycled)
    return ordered, cycled


def _sort_key(t: TaskInput) -> tuple[int, float, int, str]:
    """Stable ordering: hard-deadline first, then priority desc, then duration.

    The trailing title makes orderings deterministic across runs.
    """
    has_deadline = 0 if t.deadline_at is not None else 1
    deadline_score = t.deadline_at.timestamp() if t.deadline_at else 1e15
    return (has_deadline, deadline_score, -t.priority, t.title)


def _focus_kind_for_slot(
    slot_start: datetime, focus_windows: list[FocusWindow]
) -> FocusKind | None:
    for fw in focus_windows:
        if fw.start <= slot_start < fw.end:
            return fw.kind
    return None


def _score_slot(
    *,
    task: TaskInput,
    slot_start: datetime,
    chunk_minutes: int,
    is_after_meeting: bool,
    focus_windows: list[FocusWindow],
    prefs: PreferencesInput,
    biometric_factor: float,
    consecutive_minutes_so_far: int,
    horizon_origin: datetime,
) -> float:
    score = 0.0
    kind = _focus_kind_for_slot(slot_start, focus_windows)
    if kind is not None:
        if kind == task.focus_required:
            score += _W_FOCUS_MATCH
        else:
            score += _W_FOCUS_MISMATCH

    if is_after_meeting:
        score += _W_BUFFER_HONOURED

    hour_of_day = slot_start.astimezone(slot_start.tzinfo).hour
    if 9 <= hour_of_day <= 11 and task.focus_required == "deep":
        score += _W_EARLY_DAY

    if (
        consecutive_minutes_so_far + chunk_minutes
        > prefs.max_continuous_work_minutes
    ):
        score += _W_OVER_CONTINUOUS_LIMIT

    if biometric_factor < 0.5 and task.focus_required == "deep":
        score += _W_BIOMETRIC_LOW * (1.0 - biometric_factor)

    # Earlier slots are preferred. We measure delay in full days from
    # the horizon origin (typically "now"), so a slot one full day later
    # costs `_W_PER_DAY_DELAY`. Below 1 full day the tiebreaker takes
    # over.
    days_delay = max(0, (slot_start - horizon_origin).total_seconds() / 86400.0)
    score += _W_PER_DAY_DELAY * days_delay

    score += float(task.priority)
    return score


def _consume_interval(
    free: list[tuple[datetime, datetime, bool]],
    block_start: datetime,
    block_end: datetime,
) -> list[tuple[datetime, datetime, bool]]:
    out: list[tuple[datetime, datetime, bool]] = []
    for s, e, am in free:
        if e <= block_start or s >= block_end:
            out.append((s, e, am))
            continue
        if s < block_start:
            out.append((s, block_start, am))
        if e > block_end:
            out.append((block_end, e, False))
    return [
        (s, e, am)
        for (s, e, am) in out
        if (e - s) >= timedelta(minutes=_MIN_SLOT_MINUTES)
    ]


def _round_up_to_grid(dt: datetime) -> datetime:
    minutes = (dt.minute // _GRID_MINUTES) * _GRID_MINUTES
    base = dt.replace(minute=minutes, second=0, microsecond=0)
    if base < dt:
        base = base + timedelta(minutes=_GRID_MINUTES)
    return base


def _candidate_starts(
    *,
    free_start: datetime,
    free_end: datetime,
    chunk: timedelta,
    earliest_at: datetime | None,
) -> list[datetime]:
    """Grid-aligned candidate start times inside ``[free_start, free_end]``."""
    lower = free_start
    if earliest_at and earliest_at > lower:
        lower = earliest_at
    lower = _round_up_to_grid(lower)
    starts: list[datetime] = []
    cur = lower
    last_start = free_end - chunk
    while cur <= last_start:
        starts.append(cur)
        cur = cur + timedelta(minutes=_GRID_MINUTES)
    return starts


def schedule(
    *,
    tasks: list[TaskInput],
    fixed: list[FixedBlock],
    working: list[WorkingWindow],
    focus_windows: list[FocusWindow],
    prefs: PreferencesInput | None = None,
    biometric_factor: float = 1.0,
    horizon_origin: datetime | None = None,
) -> SchedulingResult:
    """Plan ``tasks`` into ``working`` minus ``fixed``.

    The algorithm:

    1. Topo-sort tasks by dependencies.
    2. Build free intervals from working windows minus fixed blocks.
    3. For each task (in order), find the best chunk (or chunks for
       splittables) by scoring every grid-aligned candidate start. Place,
       remove from free, repeat.
    """
    prefs = prefs or PreferencesInput()
    if not tasks:
        return SchedulingResult()

    if horizon_origin is None:
        horizon_origin = working[0].start if working else datetime.now()
    ordered, cycled = _topo_order_tasks(tasks)
    result = SchedulingResult()
    for tid in cycled:
        # Find the task name for a nicer message.
        title = next((t.title for t in tasks if t.id == tid), "task")
        result.unscheduled.append((tid, title, "dependency cycle"))

    free = _free_intervals(working, fixed)
    placed_per_task: dict[UUID, list[ScheduledChunk]] = {}
    # When a dependency is unscheduled, downstream tasks must be too.
    failed: set[UUID] = set(cycled)

    for task in ordered:
        if task.id in failed:
            continue

        if any(dep in failed for dep in task.dependencies):
            result.unscheduled.append(
                (task.id, task.title, "depends on unscheduled task")
            )
            failed.add(task.id)
            continue

        deps_end = max(
            (
                chunk.end
                for dep in task.dependencies
                for chunk in placed_per_task.get(dep, [])
            ),
            default=None,
        )
        earliest = task.earliest_at
        if deps_end is not None and (earliest is None or deps_end > earliest):
            earliest = deps_end

        remaining = task.duration_minutes
        chunk_min = task.min_chunk_minutes if task.splittable else remaining
        chunks: list[ScheduledChunk] = []
        consecutive_minutes = 0
        chunk_index = 0

        # Greedy multi-chunk loop. For non-splittables this runs at most once.
        while remaining >= chunk_min and remaining > 0:
            # Plan the longest chunk we can still fit this iteration.
            this_chunk = remaining if not task.splittable else min(
                remaining,
                max(chunk_min, prefs.max_continuous_work_minutes),
            )

            # Collect all candidate slots, score them, pick the best.
            best: tuple[float, int, datetime, datetime] | None = None
            chunk_td = timedelta(minutes=this_chunk)
            for idx, (fs, fe, after_meeting) in enumerate(free):
                if task.deadline_at and fs >= task.deadline_at:
                    continue
                # Honour buffer-after-meeting by pushing the candidate start.
                effective_start = fs
                if after_meeting and prefs.buffer_after_meeting_minutes > 0:
                    effective_start = effective_start + timedelta(
                        minutes=prefs.buffer_after_meeting_minutes
                    )
                if (fe - effective_start) < chunk_td:
                    continue
                # Break separation between task chunks is enforced after a
                # chunk is placed by consuming `[c_start - break, c_end + break]`
                # from `free`, so we don't need any additional check here.
                for cand_start in _candidate_starts(
                    free_start=effective_start,
                    free_end=fe,
                    chunk=chunk_td,
                    earliest_at=earliest,
                ):
                    cand_end = cand_start + chunk_td
                    if task.deadline_at and cand_end > task.deadline_at:
                        continue
                    score = _score_slot(
                        task=task,
                        slot_start=cand_start,
                        chunk_minutes=this_chunk,
                        is_after_meeting=after_meeting,
                        focus_windows=focus_windows,
                        prefs=prefs,
                        biometric_factor=biometric_factor,
                        consecutive_minutes_so_far=consecutive_minutes,
                        horizon_origin=horizon_origin,
                    )
                    # Tie-break: earlier start wins.
                    candidate_key = (-score, int(cand_start.timestamp()))
                    if (
                        best is None
                        or candidate_key < (-best[0], int(best[2].timestamp()))
                    ):
                        best = (score, idx, cand_start, cand_end)
            if best is None:
                break

            score, _idx, c_start, c_end = best
            chunk = ScheduledChunk(
                task_id=task.id,
                title=task.title,
                start=c_start,
                end=c_end,
                focus_required=task.focus_required,
                chunk_index=chunk_index,
                chunk_total=1,
                score=score,
                reason=_explain_chunk(task, c_start, _focus_kind_for_slot(c_start, focus_windows)),
            )
            chunks.append(chunk)
            # Carve out the chunk *plus* the min-break buffer on both sides
            # so future placements (this task's other chunks, and other
            # tasks) automatically keep their distance. We only carve the
            # break around the chunk itself — not against meetings, which
            # use their own ``buffer_after_meeting_minutes``.
            break_td = timedelta(minutes=max(0, prefs.min_break_minutes))
            free = _consume_interval(free, c_start - break_td, c_end + break_td)
            remaining -= this_chunk
            consecutive_minutes = this_chunk
            chunk_index += 1
            if not task.splittable:
                break

        if not chunks:
            failed.add(task.id)
            result.unscheduled.append(
                (task.id, task.title, "no free slot before deadline")
            )
            continue

        if remaining > 0:
            # Splittable task we couldn't finish — record what we got, flag the rest.
            failed.add(task.id)
            result.unscheduled.append(
                (task.id, task.title, f"only fit {task.duration_minutes - remaining}m of {task.duration_minutes}m")
            )

        for c in chunks:
            c.chunk_total = len(chunks)
        placed_per_task[task.id] = chunks
        result.scheduled.extend(chunks)
        result.total_score += sum(c.score for c in chunks)

    return result


def _explain_chunk(
    task: TaskInput, slot_start: datetime, focus_kind: FocusKind | None
) -> str:
    bits = [f"placed at {slot_start.strftime('%a %H:%M')}"]
    if focus_kind:
        bits.append(
            f"in {focus_kind} window"
            + (" (match)" if focus_kind == task.focus_required else " (best available)")
        )
    if task.deadline_at:
        bits.append(f"deadline {task.deadline_at.strftime('%a %H:%M')}")
    if task.priority:
        bits.append(f"priority {task.priority}")
    return ", ".join(bits)
