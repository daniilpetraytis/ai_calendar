"""Arq worker entry point: cron jobs for sync, classification, and daily briefings."""

from __future__ import annotations

import logging
from datetime import UTC, date as date_cls, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import and_, select

from app.biometrics import advisor, service as bio_service
from app.calendar import service as cal_service
from app.calendar.service import list_events as list_events_in_window
from app.categorize.service import classify_pending_llm
from app.config import get_settings
from app.db import get_sessionmaker
from app.db.models import (
    DailyBriefing,
    Event,
    Integration,
    IntegrationProvider,
    User,
)
from app.notifications import push_to_user

log = logging.getLogger(__name__)

async def startup(ctx):
    """Arq lifecycle hook called once when the worker process starts."""
    log.info("worker.startup")

async def shutdown(ctx):
    """Arq lifecycle hook called once when the worker process exits."""
    log.info("worker.shutdown")

def _user_tz(user):
    """Resolve a user's IANA timezone, falling back to UTC."""
    try:
        return ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")

async def _sync_provider(
    provider,
    sync_fn,
):
    """Run ``sync_fn`` for every user with the given integration provider, isolating failures."""
    sm = get_sessionmaker()
    total = 0
    failed = 0
    async with sm() as session:
        integrations = (
            await session.execute(
                select(Integration).where(Integration.provider == provider)
            )
        ).scalars().all()
        for integ in integrations:
            user = await session.get(User, integ.user_id)
            if user is None:
                continue
            try:
                count = await sync_fn(session, user)
                total += count
                await session.commit()
            except Exception as exc:
                await session.rollback()
                failed += 1
                log.warning(
                    "sync_failed",
                    extra={
                        "provider": provider.value,
                        "user_id": str(user.id),
                        "error": str(exc),
                    },
                )
    return {"upserted": total, "failed_users": failed}

async def sync_all_yandex_calendars(ctx):
    """Cron job: pull recent events from Yandex Calendar for every connected user."""
    return await _sync_provider(
        IntegrationProvider.YANDEX_CALENDAR, cal_service.sync_from_yandex
    )

async def classify_pending_for_all_users(ctx):
    """Cron job: run the LLM classifier over still-uncategorized events for every user."""
    sm = get_sessionmaker()
    total = 0
    failed = 0
    async with sm() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            try:
                count = await classify_pending_llm(session, user)
                if count:
                    await session.commit()
                    total += count
                    log.info(
                        "classify_worker_done",
                        extra={"user_id": str(user.id), "classified": count},
                    )
            except Exception as exc:
                await session.rollback()
                failed += 1
                log.warning(
                    "classify_worker_failed",
                    extra={"user_id": str(user.id), "error": str(exc)},
                )
    return {"classified": total, "failed_users": failed}

async def sync_all_whoop_users(ctx):
    """Cron job: sync biometrics from Whoop and send the morning briefing when due."""
    sm = get_sessionmaker()
    settings = get_settings()
    synced = 0
    failed = 0
    pushes_sent = 0

    async with sm() as session:
        rows = (
            await session.execute(
                select(Integration).where(
                    Integration.provider == IntegrationProvider.WHOOP
                )
            )
        ).scalars().all()
        for integ in rows:
            user = await session.get(User, integ.user_id)
            if user is None:
                continue
            try:
                result = await bio_service.sync_from_whoop(
                    session, user, days_back=7
                )
                synced += 1

                tz = _user_tz(user)
                now_local = datetime.now(tz)
                local_today = now_local.date()
                already_sent = await bio_service.has_briefing(
                    session, user, local_date=local_today, kind="morning"
                )
                in_window = advisor.is_within_morning_window(
                    now=now_local,
                    tz=tz,
                    min_hour=settings.morning_push_min_local_hour,
                    max_hour=settings.morning_push_max_local_hour,
                )
                should_push = (not already_sent) and in_window and (
                    result.new_recovery_today
                    or result.today_recovery_score is not None
                )
                if should_push:
                    sent = await _send_morning_push_inline(
                        session, user, local_date=local_today
                    )
                    if sent:
                        pushes_sent += 1
                await session.commit()
            except Exception as exc:
                await session.rollback()
                failed += 1
                log.warning(
                    "whoop_sync_failed",
                    extra={"user_id": str(user.id), "error": str(exc)},
                )

    return {"synced": synced, "failed": failed, "pushes_sent": pushes_sent}

async def _send_morning_push_inline(
    session, user, *, local_date
):
    """Build and deliver the morning briefing for a user, recording it in ``daily_briefings``."""
    tz = _user_tz(user)
    snap = await bio_service.get_today_snapshot(session, user)
    history = await bio_service.get_history(session, user, days=14)

    # Today's events in user-local TZ.
    day_start_utc = datetime.combine(local_date, time(0, 0), tzinfo=tz).astimezone(UTC)
    day_end_utc = day_start_utc + timedelta(days=1)
    today_events = await list_events_in_window(
        session, user, start=day_start_utc, end=day_end_utc
    )

    yesterday = local_date - timedelta(days=1)
    yesterday_briefing = await bio_service.find_briefing(
        session, user, local_date=yesterday, kind="evening"
    )

    msg = advisor.build_morning_message(
        advisor.MorningContext(
            user_tz=tz,
            local_date=local_date,
            snapshot=snap,
            today_events=today_events,
            yesterday_briefing=yesterday_briefing,
        )
    )

    row = DailyBriefing(
        tenant_id=user.tenant_id,
        user_id=user.id,
        date=local_date,
        kind="morning",
        sent_at=None,
        recovery_band=msg.get("recovery_band"),
        recovery_score=msg.get("recovery_score"),
        summary_text=msg["text"],
    )
    session.add(row)
    await session.flush()

    if user.telegram_user_id is None:
        return False

    delivered = await push_to_user(user, msg["text"])
    if delivered:
        row.sent_at = datetime.now(UTC)
    _ = bio_service.summarize_for_agent(snap, history)
    return delivered

async def detect_and_send_evening_prompts(ctx):
    """Cron job: send the end-of-day mood prompt to each Telegram-linked user when ready."""
    sm = get_sessionmaker()
    settings = get_settings()
    sent = 0
    skipped = 0

    async with sm() as session:
        users = (
            await session.execute(
                select(User).where(User.telegram_user_id.isnot(None))
            )
        ).scalars().all()
        for user in users:
            try:
                if await _maybe_send_evening_prompt(session, user, settings):
                    sent += 1
                else:
                    skipped += 1
                await session.commit()
            except Exception as exc:
                await session.rollback()
                log.warning(
                    "evening_prompt_failed",
                    extra={"user_id": str(user.id), "error": str(exc)},
                )

    return {"sent": sent, "skipped": skipped}

async def _maybe_send_evening_prompt(
    session, user, settings
):
    """Decide whether to send the evening prompt now and send it; return whether one was delivered."""
    tz = _user_tz(user)
    now_local = datetime.now(tz)
    today = now_local.date()

    # Don't ask after our hard cutoff hour.
    if now_local.hour >= settings.evening_prompt_max_local_hour:
        return False

    # Already sent / already answered? Nothing to do.
    existing = await bio_service.find_briefing(
        session, user, local_date=today, kind="evening"
    )
    if existing is not None and existing.sent_at is not None:
        return False

    # Find last in-day event end in local TZ.
    day_start_utc = datetime.combine(today, time(0, 0), tzinfo=tz).astimezone(UTC)
    day_end_utc = day_start_utc + timedelta(days=1)
    rows = (
        await session.execute(
            select(Event)
            .where(
                and_(
                    Event.user_id == user.id,
                    Event.start_at < day_end_utc,
                    Event.end_at > day_start_utc,
                )
            )
        )
    ).scalars().all()
    last_end_local = None
    for ev in rows:
        if ev.all_day:
            continue
        if (ev.category or "").lower() == "sleep":
            continue
        end_local = ev.end_at.astimezone(tz)
        # We only count events that actually finished today.
        if end_local.date() != today:
            continue
        if last_end_local is None or end_local > last_end_local:
            last_end_local = end_local

    buffer = timedelta(minutes=settings.evening_prompt_after_last_event_minutes)
    if last_end_local is not None:
        trigger_at_local = last_end_local + buffer
    else:
        # No events today — use the fallback hour.
        trigger_at_local = datetime.combine(
            today,
            time(settings.evening_prompt_fallback_local_hour, 0),
            tzinfo=tz,
        )

    if now_local < trigger_at_local:
        return False

    text = "Как день?"
    keyboard = [
        [
            {"text": "😴 легко", "callback_data": "eve:1"},
            {"text": "🙂 ок", "callback_data": "eve:2"},
            {"text": "🥵 тяжко", "callback_data": "eve:3"},
        ]
    ]

    # Pre-record the briefing so a duplicate tick can't dupe-send.
    if existing is None:
        row = DailyBriefing(
            tenant_id=user.tenant_id,
            user_id=user.id,
            date=today,
            kind="evening",
            sent_at=None,
            summary_text=text,
        )
        session.add(row)
        await session.flush()
    else:
        row = existing

    delivered = await push_to_user(user, text, keyboard=keyboard)
    if delivered:
        row.sent_at = datetime.now(UTC)
        return True
    return False

_settings = get_settings()

class WorkerSettings:
    """Arq worker configuration: registered functions, cron schedule, and lifecycle hooks."""
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    functions = [
        sync_all_yandex_calendars,
        sync_all_whoop_users,
        detect_and_send_evening_prompts,
        classify_pending_for_all_users,
    ]
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [
        cron(sync_all_yandex_calendars, minute={5, 15, 25, 35, 45, 55}),
        cron(classify_pending_for_all_users, minute={2, 12, 22, 32, 42, 52}),
        cron(sync_all_whoop_users, minute={7, 37}),
        cron(detect_and_send_evening_prompts, minute={3, 8, 13, 18, 23, 28, 33, 38, 43, 48, 53, 58}),
    ]
