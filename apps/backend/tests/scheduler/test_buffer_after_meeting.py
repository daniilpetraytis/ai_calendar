"""Buffer after meeting: don't start a deep task one second after a meeting."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.scheduler.models import FixedBlock, PreferencesInput, TaskInput
from app.scheduler.planner import schedule

from .conftest import single_day_working_window, standard_focus_windows, utc

def test_no_task_starts_immediately_after_a_meeting():
    meeting = FixedBlock(
        start=utc(hour=9),
        end=utc(hour=10),
        title="Standup",
        is_meeting=True,
    )
    task = TaskInput(
        id=uuid4(),
        title="Focus",
        duration_minutes=60,
        focus_required="shallow",
    )
    out = schedule(
        tasks=[task],
        fixed=[meeting],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
        prefs=PreferencesInput(buffer_after_meeting_minutes=15),
    )
    assert len(out.scheduled) == 1
    chunk = out.scheduled[0]
    assert chunk.start >= meeting.end + timedelta(minutes=15)

def test_zero_buffer_allows_back_to_back():
    meeting = FixedBlock(
        start=utc(hour=9),
        end=utc(hour=10),
        title="Standup",
        is_meeting=True,
    )
    task = TaskInput(
        id=uuid4(),
        title="Focus",
        duration_minutes=60,
        focus_required="shallow",
    )
    out = schedule(
        tasks=[task],
        fixed=[meeting],
        working=single_day_working_window(),
        focus_windows=standard_focus_windows(),
        prefs=PreferencesInput(buffer_after_meeting_minutes=0),
    )
    assert len(out.scheduled) == 1
    chunk = out.scheduled[0]
    # Acceptable to start exactly at meeting.end.
    assert chunk.start >= meeting.end
