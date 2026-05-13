"""Application-layer service over Whoop biometrics — sync, snapshot storage, and event-linking."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from datetime import UTC, date as date_cls, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.biometrics.whoop import (
    WhoopClient,
    WhoopRecovery,
    WhoopSleep,
    WhoopTokenSet,
    WhoopWorkout,
    refresh_access_token,
    whoop_sport_name,
)
from app.config import get_settings
from app.db.models import (
    BiometricsSnapshot,
    DailyBriefing,
    Event,
    EventSource,
    Integration,
    IntegrationProvider,
    User,
)
from app.security import decrypt, encrypt

log = logging.getLogger(__name__)

def recovery_band(recovery_score):
    """Bucket a 0-100 Whoop recovery score into ``green`` (≥67) / ``yellow`` / ``red``."""
    if recovery_score is None:
        return None
    s = int(recovery_score)
    if s >= 67:
        return "green"
    if s >= 34:
        return "yellow"
    return "red"

class WhoopNotConnected(RuntimeError):
    """Raised when a Whoop operation is attempted without a linked integration."""

    pass

async def get_whoop_integration(
    session, user
):
    """Return the user's Whoop ``Integration`` row, or ``None`` if not connected."""
    return (
        await session.execute(
            select(Integration).where(
                and_(
                    Integration.user_id == user.id,
                    Integration.provider == IntegrationProvider.WHOOP,
                )
            )
        )
    ).scalar_one_or_none()

async def _ensure_fresh_whoop_token(
    session, integration
):
    """Return a valid Whoop access token, refreshing and persisting it when within 5 minutes of expiry."""
    now = datetime.now(UTC)
    if integration.expires_at and integration.expires_at - timedelta(minutes=5) > now:
        return decrypt(integration.access_token_enc)
    if not integration.refresh_token_enc:
        raise WhoopNotConnected(
            "Whoop access token expired and no refresh token stored"
        )
    refresh_token = decrypt(integration.refresh_token_enc)
    fresh = await refresh_access_token(refresh_token)
    integration.access_token_enc = encrypt(fresh.access_token)
    if fresh.refresh_token:
        integration.refresh_token_enc = encrypt(fresh.refresh_token)
    integration.expires_at = fresh.expires_at
    if fresh.scope:
        integration.scopes = fresh.scope
    await session.flush()
    return fresh.access_token

async def get_whoop_client(
    session, user
):
    """Build a ready-to-use ``WhoopClient`` with a fresh token, or ``None`` when Whoop is not connected."""
    integration = await get_whoop_integration(session, user)
    if integration is None:
        return None
    token = await _ensure_fresh_whoop_token(session, integration)
    return WhoopClient(access_token=token)

def _user_tz(user):
    try:
        return ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")

def _local_day_to_utc_midnight(d, tz):
    local_midnight = datetime.combine(d, time(0, 0), tzinfo=tz)
    return local_midnight.astimezone(UTC)

@dataclass
class _DayBundle:
    recovery: WhoopRecovery | None = None
    sleep: WhoopSleep | None = None
    cycle_strain: float | None = None
    cycle_raw: dict[str, Any] | None = None

async def _upsert_snapshot(
    session,
    user,
    *,
    local_date,
    tz,
    bundle,
):
    """Insert or update the ``BiometricsSnapshot`` row for a single local day."""
    date_utc = _local_day_to_utc_midnight(local_date, tz)
    existing = (
        await session.execute(
            select(BiometricsSnapshot).where(
                and_(
                    BiometricsSnapshot.user_id == user.id,
                    BiometricsSnapshot.date == date_utc,
                    BiometricsSnapshot.provider == IntegrationProvider.WHOOP,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = BiometricsSnapshot(
            tenant_id=user.tenant_id,
            user_id=user.id,
            date=date_utc,
            provider=IntegrationProvider.WHOOP,
            raw={},
        )
        session.add(existing)

    raw = dict(existing.raw or {})

    if bundle.recovery is not None:
        existing.recovery_score = bundle.recovery.score
        existing.hrv_rmssd_ms = bundle.recovery.hrv_rmssd_milli
        existing.resting_heart_rate = bundle.recovery.resting_heart_rate
        raw["recovery"] = bundle.recovery.raw

    if bundle.sleep is not None:
        existing.sleep_performance = bundle.sleep.sleep_performance
        raw["sleep"] = bundle.sleep.raw
        raw["sleep_hours"] = (
            (bundle.sleep.total_asleep_minutes or 0) / 60.0
            if bundle.sleep.total_asleep_minutes
            else None
        )
        raw["sleep_efficiency"] = bundle.sleep.sleep_efficiency

    if bundle.cycle_strain is not None:
        existing.strain = bundle.cycle_strain
    if bundle.cycle_raw is not None:
        raw["cycle"] = bundle.cycle_raw

    existing.raw = raw
    return existing

_SPORT_TITLE_RU: dict[str, str] = {
    "running": "Пробежка",
    "cycling": "Велосипед",
    "swimming": "Плавание",
    "yoga": "Йога",
    "weightlifting": "Силовая тренировка",
    "strength-training": "Силовая тренировка",
    "functional-fitness": "Тренировка",
    "crossfit": "Кроссфит",
    "boxing": "Бокс",
    "tennis": "Теннис",
    "basketball": "Баскетбол",
    "football": "Футбол",
    "soccer": "Футбол",
    "hiking": "Поход",
    "walking": "Прогулка",
    "rowing": "Гребля",
    "skiing": "Лыжи",
    "snowboarding": "Сноуборд",
    "pilates": "Пилатес",
    "stretching": "Растяжка",
    "meditation": "Медитация",
}

def _workout_title(workout):
    """Pick a Russian title for an auto-created sport event from the Whoop sport name/id."""
    sport = workout.sport_name or whoop_sport_name(workout.sport_id) or ""
    sport_norm = sport.lower().strip()
    mapped = _SPORT_TITLE_RU.get(sport_norm)
    if mapped:
        return mapped
    if sport_norm:
        return f"Тренировка ({sport})"
    return "Тренировка"

async def _link_workout_to_event(
    session,
    user,
    workout,
):
    """Attach a Whoop workout to the best-matching sport event, creating one when none overlaps the workout window."""
    settings = get_settings()
    window = timedelta(minutes=settings.whoop_workout_event_match_window_minutes)
    search_start = workout.start - window
    search_end = workout.end + window

    # Already linked elsewhere? Update that one.
    already_linked = await _find_event_linked_to_workout(
        session, user, workout.workout_id
    )
    if already_linked is not None:
        already_linked.extra = _merge_workout_into_extra(already_linked.extra, workout)
        return already_linked, False

    rows = await session.execute(
        select(Event)
        .where(
            and_(
                Event.user_id == user.id,
                Event.start_at < search_end,
                Event.end_at > search_start,
            )
        )
        .order_by(Event.start_at.asc())
    )
    candidates = []
    for ev in rows.scalars().all():
        if ev.all_day:
            continue
        if ev.category == "sport":
            candidates.append(ev)

    if candidates:
        # Closest start time wins; tie-break by closest duration.
        workout_minutes = (workout.end - workout.start).total_seconds() / 60.0

        def _score(ev):
            start_delta = abs((ev.start_at - workout.start).total_seconds())
            ev_minutes = (ev.end_at - ev.start_at).total_seconds() / 60.0
            dur_delta = abs(ev_minutes - workout_minutes)
            return (start_delta, dur_delta)

        best = min(candidates, key=_score)
        best.extra = _merge_workout_into_extra(best.extra, workout)
        return best, False

    extra = _merge_workout_into_extra({}, workout)
    extra["whoop"]["auto_created"] = True
    new_event = Event(
        tenant_id=user.tenant_id,
        user_id=user.id,
        title=_workout_title(workout),
        description="Создано автоматически по данным Whoop.",
        start_at=workout.start,
        end_at=workout.end,
        all_day=False,
        source=EventSource.LOCAL,
        is_movable=False,
        category="sport",
        category_source="whoop",
        category_confidence=1.0,
        extra=extra,
    )
    session.add(new_event)
    await session.flush()
    return new_event, True

async def _find_event_linked_to_workout(
    session, user, workout_id
):
    """Return any existing event whose ``extra.whoop.workout_id`` matches ``workout_id``."""
    from sqlalchemy import text

    stmt = (
        select(Event)
        .where(Event.user_id == user.id)
        .where(text("(events.extra->'whoop'->>'workout_id') = :wid"))
        .params(wid=str(workout_id))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()

def _merge_workout_into_extra(
    extra, workout
):
    """Return a copy of ``extra`` with a ``whoop`` block describing the workout merged in."""
    new_extra = copy.deepcopy(extra or {})
    actual_minutes = max(
        1, int((workout.end - workout.start).total_seconds() // 60)
    )
    zones_minutes = {}
    for k, milli in (workout.zone_duration_milli or {}).items():
        short = k.replace("zone_", "z").replace("_milli", "")
        zones_minutes[short] = round(milli / 60_000.0, 1)
    sport = workout.sport_name or whoop_sport_name(workout.sport_id)
    new_extra["whoop"] = {
        "workout_id": workout.workout_id,
        "started_at": workout.start.isoformat(),
        "ended_at": workout.end.isoformat(),
        "actual_minutes": actual_minutes,
        "sport_id": workout.sport_id,
        "sport": sport,
        "strain": workout.strain,
        "avg_hr": workout.average_heart_rate,
        "max_hr": workout.max_heart_rate,
        "kilojoule": workout.kilojoule,
        "zones_minutes": zones_minutes,
        "synced_at": datetime.now(UTC).isoformat(),
    }
    return new_extra

@dataclass
class WhoopSyncResult:
    """Counters and flags returned by a single ``sync_from_whoop`` call."""

    days_upserted: int
    workouts_linked: int  # total workouts linked (matched + auto-created)
    workouts_auto_created: int  # subset of ``workouts_linked`` we synthesised
    today_recovery_score: int | None  # in user-local "today"
    new_recovery_today: bool  # True iff this sync is the one that landed it

async def sync_from_whoop(
    session, user, *, days_back = 7
):
    """Pull cycles / recoveries / sleep / workouts for the trailing ``days_back`` days and persist them.

    Upserts daily snapshots, links workouts to existing sport events (creating
    new events when none match), and flags whether today's recovery score
    landed in this sync."""
    integration = await get_whoop_integration(session, user)
    if integration is None:
        raise WhoopNotConnected("Whoop is not connected for this user")

    client_obj = await get_whoop_client(session, user)
    assert client_obj is not None

    tz = _user_tz(user)
    local_today = datetime.now(tz).date()

    today_utc_midnight = _local_day_to_utc_midnight(local_today, tz)
    pre_sync_today = (
        await session.execute(
            select(BiometricsSnapshot).where(
                and_(
                    BiometricsSnapshot.user_id == user.id,
                    BiometricsSnapshot.date == today_utc_midnight,
                    BiometricsSnapshot.provider == IntegrationProvider.WHOOP,
                )
            )
        )
    ).scalar_one_or_none()
    pre_recovery_score = pre_sync_today.recovery_score if pre_sync_today else None

    end_utc = (datetime.now(tz) + timedelta(days=1)).astimezone(UTC)
    start_utc = (
        datetime.combine(local_today - timedelta(days=days_back), time(0, 0), tzinfo=tz)
    ).astimezone(UTC)

    cycles = await client_obj.list_cycles(start=start_utc, end=end_utc)
    recoveries = await client_obj.list_recovery(start=start_utc, end=end_utc)
    sleeps = await client_obj.list_sleep(start=start_utc, end=end_utc)
    workouts = await client_obj.list_workouts(start=start_utc, end=end_utc)

    bundles = {}

    def _day(d):
        return d.astimezone(tz).date()

    for c in cycles:
        if c.score_state and c.score_state != "SCORED":
            continue
        d = _day(c.start)
        b = bundles.setdefault(d, _DayBundle())
        if c.strain is not None:
            b.cycle_strain = c.strain
        b.cycle_raw = c.raw

    # Map cycle_id → local day for joining recovery to its cycle.
    cycle_day_by_id = {c.cycle_id: _day(c.start) for c in cycles}
    for r in recoveries:
        d = cycle_day_by_id.get(r.cycle_id)
        if d is None:
            d = _day(r.created_at)
        b = bundles.setdefault(d, _DayBundle())
        b.recovery = r

    for s in sleeps:
        if s.nap:
            continue
        d = _day(s.end)
        b = bundles.setdefault(d, _DayBundle())
        # Prefer the longer/main sleep if multiple records (rare).
        if b.sleep is None or (
            (s.total_asleep_minutes or 0) > (b.sleep.total_asleep_minutes or 0)
        ):
            b.sleep = s

    days_upserted = 0
    for d, bundle in bundles.items():
        await _upsert_snapshot(
            session, user, local_date=d, tz=tz, bundle=bundle
        )
        days_upserted += 1

    workouts_linked = 0
    workouts_auto_created = 0
    for w in workouts:
        if w.score_state and w.score_state not in {"SCORED", "PENDING_SCORE"}:
            continue
        ev, created = await _link_workout_to_event(session, user, w)
        if ev is not None:
            workouts_linked += 1
            if created:
                workouts_auto_created += 1

    await session.flush()

    post_sync_today = (
        await session.execute(
            select(BiometricsSnapshot).where(
                and_(
                    BiometricsSnapshot.user_id == user.id,
                    BiometricsSnapshot.date == today_utc_midnight,
                    BiometricsSnapshot.provider == IntegrationProvider.WHOOP,
                )
            )
        )
    ).scalar_one_or_none()
    post_recovery_score = (
        post_sync_today.recovery_score if post_sync_today else None
    )

    new_recovery_today = bool(
        post_recovery_score is not None and pre_recovery_score is None
    )

    return WhoopSyncResult(
        days_upserted=days_upserted,
        workouts_linked=workouts_linked,
        workouts_auto_created=workouts_auto_created,
        today_recovery_score=post_recovery_score,
        new_recovery_today=new_recovery_today,
    )

async def get_today_snapshot(
    session, user
):
    """Return the user's Whoop snapshot for the current local day, or ``None`` if not yet stored."""
    tz = _user_tz(user)
    local_today = datetime.now(tz).date()
    target = _local_day_to_utc_midnight(local_today, tz)
    return (
        await session.execute(
            select(BiometricsSnapshot).where(
                and_(
                    BiometricsSnapshot.user_id == user.id,
                    BiometricsSnapshot.date == target,
                    BiometricsSnapshot.provider == IntegrationProvider.WHOOP,
                )
            )
        )
    ).scalar_one_or_none()

async def get_history(
    session, user, days
):
    """Return Whoop snapshots from the trailing ``days`` days, oldest first."""
    tz = _user_tz(user)
    local_today = datetime.now(tz).date()
    earliest = _local_day_to_utc_midnight(
        local_today - timedelta(days=max(1, days)), tz
    )
    rows = await session.execute(
        select(BiometricsSnapshot)
        .where(
            and_(
                BiometricsSnapshot.user_id == user.id,
                BiometricsSnapshot.provider == IntegrationProvider.WHOOP,
                BiometricsSnapshot.date >= earliest,
            )
        )
        .order_by(BiometricsSnapshot.date.asc())
    )
    return list(rows.scalars().all())

def summarize_for_agent(
    snapshot,
    history,
):
    """Build the recovery/sleep/strain dict consumed by the LLM agent, with a 7-day trend label."""
    if snapshot is None:
        return {"connected": True, "available": False}
    raw = snapshot.raw or {}
    sleep_hours = raw.get("sleep_hours")
    score = snapshot.recovery_score
    band = recovery_band(score)

    # 7-day average + trend (last 3 vs prior 3).
    avg7 = None
    trend = "flat"
    scored = [
        s.recovery_score for s in history if s.recovery_score is not None
    ]
    if scored:
        avg7 = round(sum(scored[-7:]) / max(1, len(scored[-7:])), 1)
    if len(scored) >= 6:
        last3 = sum(scored[-3:]) / 3.0
        prior3 = sum(scored[-6:-3]) / 3.0
        delta = last3 - prior3
        if delta >= 7:
            trend = "rising"
        elif delta <= -7:
            trend = "declining"

    return {
        "connected": True,
        "available": True,
        "recovery_score": score,
        "recovery_band": band,
        "hrv_rmssd_ms": snapshot.hrv_rmssd_ms,
        "resting_heart_rate": snapshot.resting_heart_rate,
        "sleep_performance": snapshot.sleep_performance,
        "sleep_hours": round(sleep_hours, 2) if isinstance(sleep_hours, (int, float)) else None,
        "strain_today": snapshot.strain,
        "avg_recovery_7d": avg7,
        "trend_recovery_7d": trend,
    }

async def has_briefing(
    session,
    user,
    *,
    local_date,
    kind,
):
    """Return True if a ``DailyBriefing`` of the given kind already exists for the given local date."""
    row = (
        await session.execute(
            select(DailyBriefing).where(
                and_(
                    DailyBriefing.user_id == user.id,
                    DailyBriefing.date == local_date,
                    DailyBriefing.kind == kind,
                )
            )
        )
    ).scalar_one_or_none()
    return row is not None

async def record_briefing(
    session,
    user,
    *,
    local_date,
    kind,
    summary_text,
    recovery_band_value = None,
    recovery_score_value = None,
):
    """Persist that a briefing was sent so the same one isn't dispatched twice."""
    row = DailyBriefing(
        tenant_id=user.tenant_id,
        user_id=user.id,
        date=local_date,
        kind=kind,
        sent_at=datetime.now(UTC),
        recovery_band=recovery_band_value,
        recovery_score=recovery_score_value,
        summary_text=summary_text,
    )
    session.add(row)
    await session.flush()
    return row

async def find_briefing(
    session,
    user,
    *,
    local_date,
    kind,
):
    """Return the ``DailyBriefing`` row for a date/kind pair, or ``None``."""
    return (
        await session.execute(
            select(DailyBriefing).where(
                and_(
                    DailyBriefing.user_id == user.id,
                    DailyBriefing.date == local_date,
                    DailyBriefing.kind == kind,
                )
            )
        )
    ).scalar_one_or_none()

async def get_event_workout_extra(
    session, user, event_id
):
    """Return the ``whoop`` block stored on an event's ``extra``, or ``None`` if absent or not owned by the user."""
    if isinstance(event_id, str):
        try:
            event_id = UUID(event_id)
        except ValueError:
            return None
    ev = await session.get(Event, event_id)
    if ev is None or ev.user_id != user.id:
        return None
    extra = ev.extra or {}
    whoop = extra.get("whoop")
    return whoop if isinstance(whoop, dict) else None
