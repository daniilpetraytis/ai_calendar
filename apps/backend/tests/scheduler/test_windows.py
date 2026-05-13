"""``compute_working_windows`` / ``compute_focus_windows`` happy paths."""

from __future__ import annotations

from datetime import UTC, datetime

from app.scheduler.windows import (
    DEFAULT_FOCUS_WINDOWS,
    DEFAULT_WORKING_HOURS,
    compute_focus_windows,
    compute_working_windows,
)

def test_default_working_windows_skip_weekend_in_utc_seven_days():
    horizon = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)  # Monday
    out = compute_working_windows(
        working_hours=DEFAULT_WORKING_HOURS,
        horizon_start=horizon,
        horizon_days=7,
        tz_name="UTC",
    )
    # 5 work days mon..fri
    assert len(out) == 5
    weekdays = {w.start.weekday() for w in out}
    assert weekdays == {0, 1, 2, 3, 4}

def test_focus_windows_dont_appear_on_weekend_when_filtered_by_working_hours():
    horizon = datetime(2026, 5, 16, 0, 0, tzinfo=UTC)  # Saturday
    out = compute_focus_windows(
        focus_windows=DEFAULT_FOCUS_WINDOWS,
        horizon_start=horizon,
        horizon_days=2,
        tz_name="UTC",
        working_hours=DEFAULT_WORKING_HOURS,
    )
    # Saturday + Sunday → both null → no windows.
    assert out == []

def test_local_tz_offset_is_respected():
    horizon = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
    out = compute_focus_windows(
        focus_windows=[{"start": "09:00", "end": "10:00", "kind": "deep"}],
        horizon_start=horizon,
        horizon_days=1,
        tz_name="Europe/Moscow",  # UTC+3 year-round
        working_hours=None,
    )
    assert len(out) == 1
    assert out[0].start.astimezone(UTC).hour == 6
