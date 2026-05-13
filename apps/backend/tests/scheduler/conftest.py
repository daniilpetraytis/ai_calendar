"""Shared helpers for the scheduler test suite — UTC factories and default windows."""

from __future__ import annotations

from datetime import UTC, datetime

from app.scheduler.models import FocusWindow, WorkingWindow

def utc(year=2026, month=5, day=11, hour=9, minute=0):
    """Build a timezone-aware UTC datetime with sensible defaults."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)

def single_day_working_window(
    *, start_hour = 9, end_hour = 18, day = 11, month = 5
):
    """Return a single WorkingWindow spanning one working day in UTC."""
    return [
        WorkingWindow(
            start=utc(month=month, day=day, hour=start_hour),
            end=utc(month=month, day=day, hour=end_hour),
        )
    ]

def standard_focus_windows(
    *, day = 11, month = 5
):
    """Return the canonical pair of focus windows: deep 09–12, shallow 14–17."""
    return [
        FocusWindow(
            start=utc(month=month, day=day, hour=9),
            end=utc(month=month, day=day, hour=12),
            kind="deep",
        ),
        FocusWindow(
            start=utc(month=month, day=day, hour=14),
            end=utc(month=month, day=day, hour=17),
            kind="shallow",
        ),
    ]
