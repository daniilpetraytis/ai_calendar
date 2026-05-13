"""Biometrics REST API — Whoop integration, daily snapshots, and insights."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import (
    BiometricsHistoryItem,
    BiometricsToday,
    EveningFeedbackIn,
    InsightOut,
)
from app.biometrics import insights as insights_module
from app.biometrics import service as bio_service
from app.biometrics.service import recovery_band
from app.deps import CurrentUser, DbSession

router = APIRouter()

def _user_tz(tz_name: str | None) -> ZoneInfo:
    """Resolve a user-supplied timezone name, falling back to UTC."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")

@router.get("/today", response_model=BiometricsToday)
async def biometrics_today(
    user: CurrentUser, session: DbSession
) -> BiometricsToday:
    """Return today's recovery, sleep and strain snapshot from Whoop."""
    integration = await bio_service.get_whoop_integration(session, user)
    if integration is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Whoop is not connected"
        )
    snap = await bio_service.get_today_snapshot(session, user)
    tz = _user_tz(user.timezone)
    today_local = datetime.now(tz).date()
    if snap is None:
        return BiometricsToday(
            available=False,
            date=today_local.isoformat(),
            last_synced_at=integration.updated_at,
        )
    raw = snap.raw or {}
    sleep_hours = raw.get("sleep_hours")
    if not isinstance(sleep_hours, (int, float)):
        sleep_hours = None
    return BiometricsToday(
        available=True,
        date=snap.date.astimezone(tz).date().isoformat(),
        recovery_score=snap.recovery_score,
        recovery_band=recovery_band(snap.recovery_score),
        hrv_rmssd_ms=snap.hrv_rmssd_ms,
        resting_heart_rate=snap.resting_heart_rate,
        sleep_performance=snap.sleep_performance,
        sleep_hours=round(sleep_hours, 2) if sleep_hours is not None else None,
        strain=snap.strain,
        last_synced_at=snap.updated_at,
    )

@router.get("/history", response_model=list[BiometricsHistoryItem])
async def biometrics_history(
    user: CurrentUser,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=180)] = 14,
) -> list[BiometricsHistoryItem]:
    """Return daily biometric history for the past ``days`` days."""
    rows = await bio_service.get_history(session, user, days)
    tz = _user_tz(user.timezone)
    out: list[BiometricsHistoryItem] = []
    for r in rows:
        raw = r.raw or {}
        sh = raw.get("sleep_hours")
        out.append(
            BiometricsHistoryItem(
                date=r.date.astimezone(tz).date().isoformat(),
                recovery_score=r.recovery_score,
                recovery_band=recovery_band(r.recovery_score),
                strain=r.strain,
                sleep_hours=(
                    round(float(sh), 2) if isinstance(sh, (int, float)) else None
                ),
            )
        )
    return out

@router.post("/evening-feedback")
async def evening_feedback(
    payload: EveningFeedbackIn,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, bool]:
    """Persist the user's subjective evening feedback for today's briefing."""
    tz = _user_tz(user.timezone)
    today = datetime.now(tz).date()
    row = await bio_service.find_briefing(
        session, user, local_date=today, kind="evening"
    )
    if row is None:
        row = await bio_service.record_briefing(
            session,
            user,
            local_date=today,
            kind="evening",
            summary_text=None,
        )
    row.feedback_score = payload.score
    if payload.text:
        row.feedback_text = payload.text
    row.feedback_at = datetime.now(UTC)
    return {"ok": True}

@router.get("/insights", response_model=list[InsightOut])
async def biometrics_insights(
    user: CurrentUser,
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=180)] = 30,
) -> list[InsightOut]:
    """Return derived biometric insights computed over a sliding window."""
    items = await insights_module.collect_insights(session, user, days=days)
    return [InsightOut(title=i.title, detail=i.detail) for i in items]

@router.get("/event/{event_id}/workout")
async def event_workout(
    event_id: str, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    """Return the Whoop workout payload linked to a calendar event, if any."""
    whoop = await bio_service.get_event_workout_extra(session, user, event_id)
    if whoop is None:
        return {"available": False}
    return {"available": True, **whoop}

@router.post("/sync")
async def biometrics_sync(
    user: CurrentUser,
    session: DbSession,
    days_back: Annotated[int, Query(ge=1, le=60)] = 14,
) -> dict[str, int | bool]:
    """Trigger an on-demand Whoop sync over the last ``days_back`` days."""
    if await bio_service.get_whoop_integration(session, user) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Whoop is not connected")
    result = await bio_service.sync_from_whoop(session, user, days_back=days_back)
    return {
        "days_upserted": result.days_upserted,
        "workouts_linked": result.workouts_linked,
        "workouts_auto_created": result.workouts_auto_created,
        "today_recovery_score": result.today_recovery_score or 0,
        "new_recovery_today": result.new_recovery_today,
    }
