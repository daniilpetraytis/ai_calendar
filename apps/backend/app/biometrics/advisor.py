"""Morning-briefing message builder — combines Whoop recovery, today's events, and yesterday's self-rated feedback into a single coaching line."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db.models import BiometricsSnapshot, DailyBriefing, Event

@dataclass(slots=True)
class MorningContext:
    """Bundle of inputs needed to compose a user's morning briefing."""

    user_tz: ZoneInfo
    local_date: date_cls
    snapshot: BiometricsSnapshot | None
    today_events: list[Event]
    yesterday_briefing: DailyBriefing | None  # may be None (no feedback)

def _band(score):
    if score is None:
        return None
    s = int(score)
    if s >= 67:
        return "green"
    if s >= 34:
        return "yellow"
    return "red"

def _band_emoji(band):
    return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(band or "", "")

def _hhmm(dt, tz):
    return dt.astimezone(tz).strftime("%H:%M")

def _bucket(local_dt):
    h = local_dt.hour
    if h < 12:
        return "morning"
    if h < 18:
        return "day"
    return "evening"

def _is_sport(ev):
    return (ev.category or "").lower() == "sport"

def _format_sleep_hours(hours):
    if hours is None or hours <= 0:
        return None
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h += 1
        m = 0
    return f"{h}h{m:02d}m" if m else f"{h}h"

def _free_window_minutes(events, local_date, tz):
    """Return free minutes inside the 09:00-21:00 local window after merging busy intervals."""
    day_start = datetime.combine(local_date, time(9, 0), tzinfo=tz)
    day_end = datetime.combine(local_date, time(21, 0), tzinfo=tz)

    intervals = []
    for ev in events:
        if ev.all_day:
            continue
        s = max(ev.start_at.astimezone(tz), day_start)
        e = min(ev.end_at.astimezone(tz), day_end)
        if e > s:
            intervals.append((s, e))
    intervals.sort()
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    total = (day_end - day_start).total_seconds() / 60.0
    busy = sum((e - s).total_seconds() for s, e in merged) / 60.0
    return max(0, int(total - busy))

def build_advice_line(
    *,
    band,
    has_sport,
    free_minutes,
    yesterday_score,  # 1=легко, 2=ок, 3=тяжко, None=нет данных
):
    """Pick the single Russian advice line that matches the recovery band,
    today's sport plans, free-window size, and yesterday's self-rated load."""
    if band is None:
        if has_sport and yesterday_score == 3:
            return "Вчера был тяжёлый — без recovery лучше держать тренировку лёгкой."
        if free_minutes >= 90 and yesterday_score in (None, 1, 2):
            return "Recovery ещё не пришёл — день кажется свободным, можно вкинуть лёгкое движение."
        return "Recovery ещё не пришёл — двигайся по плану, без перегрузок."

    if band == "red":
        if has_sport:
            return "Recovery 🔴 — тяжёлую тренировку лучше перенести или сделать лёгкой."
        return "Recovery 🔴 — фокус на восстановление: прогулка/растяжка, ложись пораньше."

    if band == "yellow":
        if has_sport:
            if yesterday_score == 3:
                return "Recovery 🟡 + вчерашний день был тяжёлый — тренировку лучше смягчить, zone-2."
            return "Recovery 🟡 — тренировку держи в zone-2, не максимали."
        if yesterday_score == 3:
            return "Recovery 🟡, вчера был выжатый — сегодня береги силы, день стандартный."
        if free_minutes >= 90 and yesterday_score in (None, 1, 2):
            return "Recovery 🟡 — окна свободны, можно добавить лёгкую активность."
        return "Recovery 🟡 — день стандартный, без перегрузок."

    # green
    if has_sport:
        if yesterday_score == 3:
            return "Recovery 🟢, но вчера было тяжко — иди в свой план, без новых рекордов."
        return "Recovery 🟢 — отличный день для интенсивной тренировки, можно идти в strain target."
    if free_minutes >= 90 and yesterday_score in (None, 1, 2):
        return "Recovery 🟢, окна свободны и вчера не выжали — можно добавить тренировку."
    if yesterday_score == 3:
        return "Recovery 🟢 — но вчера ты выжал день, сегодня держи темп умеренным."
    return "Recovery 🟢 — продуктивный день, можно слегка нагрузить."

def build_morning_message(ctx):
    """Compose the full morning Telegram message (greeting, biometrics, today's
    agenda, advice line) and return it with the recovery band/score for storage."""
    tz = ctx.user_tz
    snap = ctx.snapshot

    score = snap.recovery_score if snap else None
    band = _band(score)
    band_emoji = _band_emoji(band)

    lines = ["Доброе утро ☀️"]

    # Top biometric line (skipped when Whoop has nothing).
    if snap is not None and (
        score is not None
        or (snap.raw or {}).get("sleep_hours") is not None
        or snap.strain is not None
        or snap.hrv_rmssd_ms is not None
    ):
        bio_parts = []
        if score is not None:
            bio_parts.append(f"Recovery {score}% {band_emoji}".rstrip())
        sleep_hours = (snap.raw or {}).get("sleep_hours")
        sleep_str = _format_sleep_hours(sleep_hours) if isinstance(sleep_hours, (int, float)) else None
        if sleep_str:
            bio_parts.append(f"сон {sleep_str}")
        if snap.hrv_rmssd_ms:
            bio_parts.append(f"HRV {int(snap.hrv_rmssd_ms)}ms")
        if snap.resting_heart_rate:
            bio_parts.append(f"RHR {int(snap.resting_heart_rate)}")
        if bio_parts:
            lines.append(", ".join(bio_parts) + ".")

    # Today's events grouped by part-of-day.
    by_bucket = {"morning": [], "day": [], "evening": []}
    has_sport = False
    for ev in sorted(ctx.today_events, key=lambda e: e.start_at):
        if ev.all_day:
            continue
        local_start = ev.start_at.astimezone(tz)
        # Skip events that already finished.
        if ev.end_at.astimezone(tz) < datetime.now(tz):
            continue
        by_bucket[_bucket(local_start)].append(ev)
        if _is_sport(ev):
            has_sport = True

    bucket_labels = {"morning": "Утром", "day": "Днём", "evening": "Вечером"}
    has_any_event = False
    for key in ("morning", "day", "evening"):
        evs = by_bucket[key]
        if not evs:
            continue
        has_any_event = True
        lines.append("")
        lines.append(f"{bucket_labels[key]}:")
        for ev in evs[:6]:  # cap so we don't blow Telegram message limits
            mins = max(1, int((ev.end_at - ev.start_at).total_seconds() // 60))
            dur = (
                f"{mins}m" if mins < 60 else f"{mins // 60}h" + (
                    f" {mins % 60}m" if mins % 60 else ""
                )
            )
            lines.append(
                f"• {_hhmm(ev.start_at, tz)} {ev.title} ({dur})"
            )

    if not has_any_event:
        lines.append("")
        lines.append("Сегодня в календаре пусто.")

    # Advice line.
    free = _free_window_minutes(ctx.today_events, ctx.local_date, tz)
    yesterday_score = (
        ctx.yesterday_briefing.feedback_score if ctx.yesterday_briefing else None
    )
    advice = build_advice_line(
        band=band,
        has_sport=has_sport,
        free_minutes=free,
        yesterday_score=yesterday_score,
    )
    lines.append("")
    lines.append(advice)

    text = "\n".join(lines).strip()
    return {
        "text": text,
        "recovery_band": band,
        "recovery_score": score,
    }

def is_within_morning_window(
    *, now, tz, min_hour, max_hour
):
    """Return True when ``now`` falls inside the configured morning-briefing hour range in the user's timezone."""
    local = now.astimezone(tz)
    return min_hour <= local.hour < max_hour
