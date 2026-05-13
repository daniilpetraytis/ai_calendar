"""Compute working and focus time windows in UTC from per-user local-time preferences."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.scheduler.models import FocusKind, FocusWindow, WorkingWindow

_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def _parse_hhmm(value):
    """Parse an ``"HH:MM"`` string into a ``time``."""
    h, m = value.split(":")
    return time(int(h), int(m))

def _resolve_tz(tz_name):
    """Resolve an IANA tz name to a ``ZoneInfo``, falling back to UTC on error."""
    if not tz_name:
        return UTC
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return UTC

def _local_to_utc(d, t, tz):
    """Combine a local date/time in ``tz`` and convert the result to UTC."""
    return datetime.combine(d, t, tzinfo=tz).astimezone(UTC)

def compute_working_windows(
    *,
    working_hours,
    horizon_start,
    horizon_days,
    tz_name,
):
    """Expand a weekly working-hours config into ``WorkingWindow``s in UTC over the horizon."""
    tz = _resolve_tz(tz_name)
    local_start = horizon_start.astimezone(tz)
    base_day = local_start.date()

    out = []
    for offset in range(max(1, horizon_days)):
        the_day = base_day + timedelta(days=offset)
        key = _WEEKDAY_KEYS[the_day.weekday()]
        cfg = working_hours.get(key)
        if not cfg or not isinstance(cfg, dict):
            continue
        try:
            ws = _parse_hhmm(cfg["start"])
            we = _parse_hhmm(cfg["end"])
        except (KeyError, ValueError):
            continue
        start_utc = _local_to_utc(the_day, ws, tz)
        end_utc = _local_to_utc(the_day, we, tz)
        if offset == 0 and horizon_start > start_utc:
            start_utc = horizon_start
        if start_utc < end_utc:
            out.append(WorkingWindow(start=start_utc, end=end_utc))
    return out

def compute_focus_windows(
    *,
    focus_windows,
    horizon_start,
    horizon_days,
    tz_name,
    working_hours = None,
):
    """Expand focus-window definitions into ``FocusWindow``s in UTC, restricted to working days."""
    tz = _resolve_tz(tz_name)
    local_start = horizon_start.astimezone(tz)
    base_day = local_start.date()

    out = []
    for offset in range(max(1, horizon_days)):
        the_day = base_day + timedelta(days=offset)
        if working_hours is not None:
            key = _WEEKDAY_KEYS[the_day.weekday()]
            cfg = working_hours.get(key)
            if not cfg:
                continue

        for window in focus_windows:
            try:
                ws = _parse_hhmm(window["start"])
                we = _parse_hhmm(window["end"])
            except (KeyError, ValueError, TypeError):
                continue
            kind_raw = window.get("kind", "shallow")
            kind = (
                kind_raw if kind_raw in ("deep", "shallow", "admin") else "shallow"
            )
            start_utc = _local_to_utc(the_day, ws, tz)
            end_utc = _local_to_utc(the_day, we, tz)
            if offset == 0 and horizon_start > start_utc:
                start_utc = horizon_start
            if start_utc < end_utc:
                out.append(FocusWindow(start=start_utc, end=end_utc, kind=kind))
    return out

DEFAULT_WORKING_HOURS: dict[str, Any] = {
    "mon": {"start": "09:00", "end": "18:00"},
    "tue": {"start": "09:00", "end": "18:00"},
    "wed": {"start": "09:00", "end": "18:00"},
    "thu": {"start": "09:00", "end": "18:00"},
    "fri": {"start": "09:00", "end": "18:00"},
    "sat": None,
    "sun": None,
}

DEFAULT_FOCUS_WINDOWS: list[dict[str, Any]] = [
    {"start": "09:00", "end": "12:00", "kind": "deep"},
    {"start": "14:00", "end": "17:00", "kind": "shallow"},
]
