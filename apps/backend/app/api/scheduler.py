"""Scheduling preferences and auto-scheduler endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import (
    PreferencesOut,
    PreferencesUpdate,
    SchedulerProposalOut,
    SchedulerRunRequest,
    SchedulerRunResponse,
)
from app.deps import CurrentUser, DbSession
from app.scheduler.service import (
    auto_schedule_user,
    get_or_create_preferences,
    result_to_proposal,
)

router = APIRouter()

def _prefs_to_dict(prefs) -> dict:
    """Serialise a Preferences row into the wire format used by the API."""
    return {
        "working_hours": prefs.working_hours or {},
        "focus_windows": prefs.focus_windows or [],
        "min_break_minutes": prefs.min_break_minutes,
        "max_continuous_work_minutes": prefs.max_continuous_work_minutes,
        "auto_schedule_enabled": prefs.auto_schedule_enabled,
        "buffer_after_meeting_minutes": prefs.buffer_after_meeting_minutes,
    }

@router.get("/preferences", response_model=PreferencesOut)
async def read_preferences(user: CurrentUser, session: DbSession) -> PreferencesOut:
    """Return the current scheduling preferences, creating defaults on first read."""
    prefs = await get_or_create_preferences(session, user)
    return _prefs_to_dict(prefs)  # type: ignore[return-value]

@router.patch("/preferences", response_model=PreferencesOut)
async def update_preferences(
    body: PreferencesUpdate, user: CurrentUser, session: DbSession
) -> PreferencesOut:
    """Patch the user's scheduling preferences with the supplied fields."""
    prefs = await get_or_create_preferences(session, user)
    data = body.model_dump(exclude_unset=True)
    if "working_hours" in data and data["working_hours"] is not None:
        prefs.working_hours = {
            day: (entry.model_dump() if entry is not None else None)
            if hasattr(entry, "model_dump")
            else entry
            for day, entry in data["working_hours"].items()
        }
    if "focus_windows" in data and data["focus_windows"] is not None:
        prefs.focus_windows = [
            w.model_dump() if hasattr(w, "model_dump") else w
            for w in data["focus_windows"]
        ]
    for key in (
        "min_break_minutes",
        "max_continuous_work_minutes",
        "auto_schedule_enabled",
        "buffer_after_meeting_minutes",
    ):
        if key in data:
            setattr(prefs, key, data[key])
    await session.flush()
    return _prefs_to_dict(prefs)  # type: ignore[return-value]

@router.post("/run", response_model=SchedulerRunResponse)
async def run_scheduler(
    body: SchedulerRunRequest, user: CurrentUser, session: DbSession
) -> SchedulerRunResponse:
    """Run the auto-scheduler over the requested horizon, optionally applying it."""
    result, run = await auto_schedule_user(
        session,
        user,
        horizon_days=body.horizon_days,
        apply=body.apply,
        trigger="manual" if not body.apply else "manual_apply",
        biometric_factor=body.biometric_factor,
    )
    proposal = result_to_proposal(result, summary_prefix="Auto-schedule")
    return SchedulerRunResponse(
        proposal=SchedulerProposalOut(**proposal),
        applied_count=len(result.scheduled) if body.apply else 0,
        run_id=run.id,
        horizon_days=body.horizon_days,
    )
