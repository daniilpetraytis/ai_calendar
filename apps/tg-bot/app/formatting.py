"""Formatting helpers that turn backend payloads into Telegram-ready Markdown strings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from dateutil import parser as dateparser

MAX_TG_MESSAGE_LEN = 4000  # actual TG limit is 4096; leave headroom for ellipsis

def _to_local(iso, tz = None):
    """Parse an ISO timestamp and convert it to the given timezone."""
    dt = dateparser.isoparse(iso)
    if tz is not None:
        return dt.astimezone(tz)
    return dt

def truncate_for_telegram(text, *, limit = MAX_TG_MESSAGE_LEN):
    """Truncate a string to the Telegram message limit, appending an ellipsis if needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"

def format_today(events, *, tz_name = "UTC"):
    """Render today's events as a Markdown bullet list in the user's local timezone."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = UTC

    today = datetime.now(tz).date()
    todays = [
        e
        for e in events
        if _to_local(e["start_at"], tz).date() <= today
        and _to_local(e["end_at"], tz).date() >= today
    ]
    if not todays:
        return "Сегодня в календаре пусто."

    todays.sort(key=lambda e: _to_local(e["start_at"], tz))
    lines = ["📅 *Сегодня:*"]
    for e in todays:
        s = _to_local(e["start_at"], tz)
        end = _to_local(e["end_at"], tz)
        cat = e.get("category")
        cat_chip = f" · {cat}" if cat else ""
        title = e.get("title") or "(без названия)"
        lines.append(
            f"• `{s.strftime('%H:%M')}–{end.strftime('%H:%M')}` {title}{cat_chip}"
        )
    return "\n".join(lines)

def format_stats(stats):
    """Render a weekly per-category time-spent breakdown as Markdown."""
    by_cat = stats.get("by_category") or []
    total = stats.get("total_minutes") or 0
    period_label = stats.get("period_label") or "неделя"
    if total == 0:
        return f"📊 За {period_label}: пока ничего не запланировано."
    by_cat = sorted(by_cat, key=lambda x: x.get("minutes", 0), reverse=True)
    lines = [f"📊 *{period_label}*  ·  всего {_fmt_hm(total)}"]
    for item in by_cat[:10]:
        m = item.get("minutes", 0)
        if m == 0:
            continue
        name = item.get("category") or "?"
        emoji = item.get("emoji") or ""
        goal = item.get("goal_minutes_per_week")
        goal_part = f"  /  цель {_fmt_hm(goal)}" if goal else ""
        lines.append(f"{emoji} {name} — {_fmt_hm(m)}{goal_part}")
    return "\n".join(lines)

def _fmt_hm(minutes):
    """Format a duration in minutes as a compact `Xч YYм` string."""
    if not minutes:
        return "0м"
    h, m = divmod(int(minutes), 60)
    if h == 0:
        return f"{m}м"
    if m == 0:
        return f"{h}ч"
    return f"{h}ч{m:02d}м"

def format_proposal(proposal, *, tz_name = "UTC"):
    """Render an agent re-plan proposal (with per-change icons and reasons) as Markdown."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = UTC

    summary = proposal.get("summary") or "Предложение по календарю"
    changes = proposal.get("changes") or []
    lines = [f"🧭 *{summary}*", ""]
    for i, c in enumerate(changes, 1):
        op = c.get("op")
        title = c.get("title") or "(без названия)"
        ns = c.get("new_start_iso")
        ne = c.get("new_end_iso")
        time_part = ""
        if ns and ne:
            s = _to_local(ns, tz)
            e = _to_local(ne, tz)
            same_day = s.date() == e.date()
            if same_day:
                time_part = (
                    f"{s.strftime('%a %d.%m %H:%M')}–{e.strftime('%H:%M')}"
                )
            else:
                time_part = (
                    f"{s.strftime('%a %d.%m %H:%M')} → {e.strftime('%a %d.%m %H:%M')}"
                )
        icon = {
            "create": "➕",
            "move": "🔁",
            "update": "✏️",
            "delete": "🗑️",
            "skip": "•",
        }.get(op or "", "•")
        reason = c.get("reason")
        reason_part = f"\n    _{reason}_" if reason else ""
        lines.append(f"{i}. {icon} {title}  ·  {time_part}{reason_part}")
    unscheduled = proposal.get("unscheduled") or []
    if unscheduled:
        lines.append("")
        lines.append("⚠️ Не удалось распланировать:")
        for u in unscheduled:
            lines.append(f"  • {u.get('title')}")
    return truncate_for_telegram("\n".join(lines))

def format_event_card(event, *, tz_name = "UTC"):
    """Render a single event as a compact Markdown card with title, time, and category."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = UTC
    s = _to_local(event["start_at"], tz)
    e = _to_local(event["end_at"], tz)
    title = event.get("title") or "Событие"
    cat = event.get("category")
    cat_part = f" · {cat}" if cat else ""
    if s.date() == e.date():
        when = f"{s.strftime('%a %d.%m %H:%M')}–{e.strftime('%H:%M')}"
    else:
        when = f"{s.strftime('%a %d.%m %H:%M')} → {e.strftime('%a %d.%m %H:%M')}"
    return f"📌 *{title}*\n{when}{cat_part}"

def isoformat_window(*, days_ahead, tz_name = "UTC"):
    """Return ISO start/end of a window starting at today 00:00 local and `days_ahead` long."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = UTC
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days_ahead)
    return start.isoformat(), end.isoformat()
