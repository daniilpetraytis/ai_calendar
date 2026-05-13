"""Time-tracking statistics endpoints (by-day, by-category, heatmap, trends)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select

from app.api.schemas import (
    CategoryStatItem,
    DayCategoryItem,
    DayStatItem,
    HeatmapCell,
    HeatmapOut,
    StatsByCategoryOut,
    TrendItem,
    TrendsOut,
)
from app.categorize.service import get_user_categories
from app.db.models import CategoryDefinition, Event
from app.deps import CurrentUser, DbSession

router = APIRouter()

Period = Literal["day", "week", "month"]

def _user_tz(user_timezone: str) -> ZoneInfo:
    """Resolve a user-supplied timezone name, falling back to UTC."""
    try:
        return ZoneInfo(user_timezone)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")

def _period_bounds(
    period: Period, offset: int, tz: ZoneInfo
) -> tuple[datetime, datetime, str]:
    """Return UTC bounds and a label for the requested day/week/month period."""
    now_local = datetime.now(tz)

    if period == "day":
        day = now_local.date() + timedelta(days=offset)
        start_local = datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        label = day.strftime("%Y-%m-%d")

    elif period == "week":
        # ISO week: Monday = 0
        monday = now_local.date() - timedelta(days=now_local.weekday())
        monday += timedelta(weeks=offset)
        start_local = datetime(monday.year, monday.month, monday.day, 0, 0, tzinfo=tz)
        end_local = start_local + timedelta(weeks=1)
        iso = monday.isocalendar()
        label = f"{iso[0]}-W{iso[1]:02d}"

    else:  # month
        year = now_local.year
        month = now_local.month + offset
        # Normalise month overflow/underflow
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        start_local = datetime(year, month, 1, 0, 0, tzinfo=tz)
        if month == 12:
            end_local = datetime(year + 1, 1, 1, 0, 0, tzinfo=tz)
        else:
            end_local = datetime(year, month + 1, 1, 0, 0, tzinfo=tz)
        label = f"{year}-{month:02d}"

    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        label,
    )

def _duration_minutes(start: datetime, end: datetime) -> int:
    """Return the non-negative duration between two datetimes in whole minutes."""
    return max(0, int((end - start).total_seconds() / 60))

@router.get("/by-day", response_model=list[DayStatItem])
async def stats_by_day(
    user: CurrentUser,
    session: DbSession,
    period: Annotated[Period, Query()] = "week",
    offset: Annotated[int, Query(ge=-52, le=0)] = 0,
) -> list[DayStatItem]:
    """Return per-day totals broken down by category for the chosen period."""
    tz = _user_tz(user.timezone)
    start_utc, end_utc, _ = _period_bounds(period, offset, tz)

    rows = (
        await session.execute(
            select(Event).where(
                and_(
                    Event.user_id == user.id,
                    Event.start_at >= start_utc,
                    Event.start_at < end_utc,
                )
            )
        )
    ).scalars().all()

    cats = await get_user_categories(session, user)
    cat_map: dict[str, CategoryDefinition] = {c.name: c for c in cats}

    # Group by local date → category → minutes
    from collections import defaultdict
    day_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ev in rows:
        date_str = ev.start_at.astimezone(tz).date().isoformat()
        cat = ev.category or "other"
        day_cat[date_str][cat] += _duration_minutes(ev.start_at, ev.end_at)

    _DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    result: list[DayStatItem] = []

    # Walk the full period day-by-day so empty days still appear
    import datetime as _dt
    cursor = start_utc.astimezone(tz).date()
    end_date = end_utc.astimezone(tz).date()
    while cursor < end_date:
        date_str = cursor.isoformat()
        cats_for_day = day_cat.get(date_str, {})
        total = sum(cats_for_day.values())
        by_cat = [
            DayCategoryItem(
                category=cat_name,
                minutes=mins,
                color=cat_map[cat_name].color if cat_name in cat_map else "#9ca3af",
                emoji=cat_map[cat_name].emoji if cat_name in cat_map else None,
            )
            for cat_name, mins in sorted(cats_for_day.items(), key=lambda x: -x[1])
        ]
        result.append(DayStatItem(
            date=date_str,
            day_label=_DOW[cursor.weekday()],
            total_minutes=total,
            by_category=by_cat,
        ))
        cursor += _dt.timedelta(days=1)

    return result

@router.get("/by-category", response_model=StatsByCategoryOut)
async def stats_by_category(
    user: CurrentUser,
    session: DbSession,
    period: Annotated[Period, Query()] = "week",
    offset: Annotated[int, Query(ge=-52, le=0)] = 0,
) -> StatsByCategoryOut:
    """Return total minutes per category over the requested period."""
    tz = _user_tz(user.timezone)
    start_utc, end_utc, label = _period_bounds(period, offset, tz)

    rows = (
        await session.execute(
            select(Event).where(
                and_(
                    Event.user_id == user.id,
                    Event.start_at >= start_utc,
                    Event.start_at < end_utc,
                )
            )
        )
    ).scalars().all()

    totals: dict[str, int] = {}
    for ev in rows:
        cat = ev.category or "other"
        totals[cat] = totals.get(cat, 0) + _duration_minutes(ev.start_at, ev.end_at)

    cats = await get_user_categories(session, user)
    cat_map: dict[str, CategoryDefinition] = {c.name: c for c in cats}

    items: list[CategoryStatItem] = []
    for cat_name, minutes in sorted(totals.items(), key=lambda x: -x[1]):
        defn = cat_map.get(cat_name)
        items.append(
            CategoryStatItem(
                category=cat_name,
                minutes=minutes,
                color=defn.color if defn else "#9ca3af",
                emoji=defn.emoji if defn else None,
                goal_minutes_per_week=defn.goal_minutes_per_week if defn else None,
            )
        )

    return StatsByCategoryOut(
        period_label=label,
        period_start=start_utc,
        period_end=end_utc,
        total_minutes=sum(totals.values()),
        by_category=items,
    )

@router.get("/heatmap", response_model=HeatmapOut)
async def stats_heatmap(
    user: CurrentUser,
    session: DbSession,
    period: Annotated[Period, Query()] = "week",
    offset: Annotated[int, Query(ge=-52, le=0)] = 0,
) -> HeatmapOut:
    """Return a busy-minutes heatmap across day-of-week and hour-of-day."""
    tz = _user_tz(user.timezone)
    start_utc, end_utc, label = _period_bounds(period, offset, tz)

    rows = (
        await session.execute(
            select(Event).where(
                and_(
                    Event.user_id == user.id,
                    Event.start_at >= start_utc,
                    Event.start_at < end_utc,
                )
            )
        )
    ).scalars().all()

    # {(day_of_week, hour): minutes}  day_of_week: 0=Mon … 6=Sun
    grid: dict[tuple[int, int], int] = {}
    for ev in rows:
        local_start = ev.start_at.astimezone(tz)
        dow = local_start.weekday()  # 0=Mon
        hour = local_start.hour
        mins = _duration_minutes(ev.start_at, ev.end_at)
        key = (dow, hour)
        grid[key] = grid.get(key, 0) + mins

    cells = [
        HeatmapCell(day=day, hour=hour, minutes=mins)
        for (day, hour), mins in sorted(grid.items())
        if mins > 0
    ]
    return HeatmapOut(period_label=label, cells=cells)

@router.get("/trends", response_model=TrendsOut)
async def stats_trends(
    user: CurrentUser,
    session: DbSession,
    period: Annotated[Period, Query()] = "week",
    offset: Annotated[int, Query(ge=-52, le=-1)] = -1,
) -> TrendsOut:
    """Return per-category trend deltas between the previous and current period."""
    tz = _user_tz(user.timezone)
    prev_start, prev_end, prev_label = _period_bounds(period, offset, tz)
    curr_start, curr_end, curr_label = _period_bounds(period, offset + 1, tz)

    rows = (
        await session.execute(
            select(Event).where(
                and_(
                    Event.user_id == user.id,
                    Event.start_at >= prev_start,
                    Event.start_at < curr_end,
                )
            )
        )
    ).scalars().all()

    prev_totals: dict[str, int] = {}
    curr_totals: dict[str, int] = {}
    for ev in rows:
        cat = ev.category or "other"
        mins = _duration_minutes(ev.start_at, ev.end_at)
        if prev_start <= ev.start_at < prev_end:
            prev_totals[cat] = prev_totals.get(cat, 0) + mins
        else:
            curr_totals[cat] = curr_totals.get(cat, 0) + mins

    cats = await get_user_categories(session, user)
    cat_map: dict[str, CategoryDefinition] = {c.name: c for c in cats}

    all_cats = set(prev_totals) | set(curr_totals)
    items: list[TrendItem] = []
    for cat_name in sorted(all_cats):
        curr = curr_totals.get(cat_name, 0)
        prev = prev_totals.get(cat_name, 0)
        delta = curr - prev
        delta_pct = round((delta / prev) * 100, 1) if prev > 0 else None
        defn = cat_map.get(cat_name)
        items.append(
            TrendItem(
                category=cat_name,
                color=defn.color if defn else "#9ca3af",
                emoji=defn.emoji if defn else None,
                current_minutes=curr,
                previous_minutes=prev,
                delta_minutes=delta,
                delta_pct=delta_pct,
            )
        )

    # Sort by absolute change descending
    items.sort(key=lambda x: abs(x.delta_minutes), reverse=True)

    return TrendsOut(
        period_label=curr_label,
        previous_label=prev_label,
        items=items,
    )
