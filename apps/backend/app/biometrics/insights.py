"""Correlate user-reported daily feedback with Whoop snapshots and event load to surface coaching insights."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date as date_cls, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BiometricsSnapshot,
    DailyBriefing,
    Event,
    IntegrationProvider,
    User,
)

@dataclass
class Insight:
    """One human-readable observation about the user's recent load and recovery."""

    title: str
    detail: str

def _user_tz(user):
    try:
        return ZoneInfo(user.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")

def _local_midnight_utc(d, tz):
    return datetime.combine(d, time(0, 0), tzinfo=tz).astimezone(UTC)

async def collect_insights(
    session,
    user,
    *,
    days = 30,
):
    """Build a list of ``Insight``s for the last ``days`` days by joining daily
    feedback with Whoop snapshots and meeting/work load. Returns an empty list
    when there is no feedback to anchor the analysis."""
    tz = _user_tz(user)
    today = datetime.now(tz).date()
    earliest = today - timedelta(days=days)

    feedback_rows = (
        await session.execute(
            select(DailyBriefing).where(
                and_(
                    DailyBriefing.user_id == user.id,
                    DailyBriefing.kind == "evening",
                    DailyBriefing.feedback_score.isnot(None),
                    DailyBriefing.date >= earliest,
                )
            )
        )
    ).scalars().all()

    if not feedback_rows:
        return []

    snapshot_rows = (
        await session.execute(
            select(BiometricsSnapshot).where(
                and_(
                    BiometricsSnapshot.user_id == user.id,
                    BiometricsSnapshot.provider == IntegrationProvider.WHOOP,
                    BiometricsSnapshot.date >= _local_midnight_utc(earliest, tz),
                )
            )
        )
    ).scalars().all()
    snap_by_date = {}
    for s in snapshot_rows:
        snap_by_date[s.date.astimezone(tz).date()] = s

    event_rows = (
        await session.execute(
            select(Event).where(
                and_(
                    Event.user_id == user.id,
                    Event.start_at >= _local_midnight_utc(earliest, tz),
                )
            )
        )
    ).scalars().all()
    meetings_by_date = Counter()
    for ev in event_rows:
        if ev.all_day:
            continue
        if (ev.category or "").lower() not in {"meeting", "work"}:
            continue
        d = ev.start_at.astimezone(tz).date()
        meetings_by_date[d] += 1

    insights = []

    tough = [r for r in feedback_rows if r.feedback_score == 3]
    tough_with_strain = [
        snap_by_date[r.date].strain
        for r in tough
        if r.date in snap_by_date and snap_by_date[r.date].strain is not None
    ]
    if len(tough_with_strain) >= 3:
        avg_strain = sum(tough_with_strain) / len(tough_with_strain)
        if avg_strain >= 14:
            insights.append(
                Insight(
                    title="Тяжёлые дни ↔ strain",
                    detail=(
                        f"{len(tough_with_strain)} дней с оценкой 🥵 шли при средней "
                        f"strain {avg_strain:.1f}. Можно целиться в strain ≤14 в будни."
                    ),
                )
            )

    good_days = [
        r for r in feedback_rows if r.feedback_score in (1, 2)
    ]
    good_recoveries = [
        snap_by_date[r.date].recovery_score
        for r in good_days
        if r.date in snap_by_date and snap_by_date[r.date].recovery_score is not None
    ]
    if len(good_recoveries) >= 3:
        avg_rec = sum(good_recoveries) / len(good_recoveries)
        if avg_rec >= 60:
            insights.append(
                Insight(
                    title="Хорошие дни ↔ recovery",
                    detail=(
                        f"Дни 😴/🙂 чаще всего идут при recovery ≥ {int(avg_rec)}%. "
                        "Зелёное утро коррелирует с лёгким днём."
                    ),
                )
            )

    tough_meeting_counts = [
        meetings_by_date.get(r.date, 0) for r in tough
    ]
    if tough_meeting_counts and (
        sum(tough_meeting_counts) / len(tough_meeting_counts) >= 4
    ):
        insights.append(
            Insight(
                title="Тяжёлые дни ↔ встречи",
                detail=(
                    f"В среднем по 🥵 дням было "
                    f"{sum(tough_meeting_counts) / len(tough_meeting_counts):.1f} встреч. "
                    "Стоит лимитировать ≤3-4 встречи в один день."
                ),
            )
        )

    counts = Counter(r.feedback_score for r in feedback_rows)
    insights.append(
        Insight(
            title=f"Самочувствие за {days} дней",
            detail=(
                f"😴 легко: {counts.get(1, 0)}, "
                f"🙂 ок: {counts.get(2, 0)}, "
                f"🥵 тяжко: {counts.get(3, 0)}."
            ),
        )
    )

    return insights

def insights_to_dict(items):
    """Serialise ``Insight`` objects into plain ``{title, detail}`` dicts for the API."""
    return [{"title": i.title, "detail": i.detail} for i in items]
