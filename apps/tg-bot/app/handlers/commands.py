"""Built-in slash commands router: /help, /today, /stats."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import backend_client
from app.formatting import (
    format_stats,
    format_today,
    isoformat_window,
    truncate_for_telegram,
)

log = logging.getLogger(__name__)

router = Router(name="commands")

async def _require_linked(msg):
    """Return the linked user info or reply with a link prompt and return None."""
    if msg.from_user is None:
        return None
    info = await backend_client.lookup_telegram_user(msg.from_user.id)
    if info is None:
        await msg.answer(
            "Аккаунт не привязан. Открой веб-приложение → Settings → Telegram → Connect."
        )
        return None
    return info

@router.message(Command("help"))
async def cmd_help(msg):
    """Reply to /help with a short usage cheatsheet."""
    await msg.answer(
        "*AI Calendar бот*\n"
        "Просто напиши, что нужно сделать с календарём — поставить событие, "
        "перенести встречу, распланировать день/неделю, что у тебя в стате.\n\n"
        "*Команды:*\n"
        "• /today — что у тебя сегодня\n"
        "• /stats — расход времени за неделю по категориям\n"
        "• /help — эта подсказка\n\n"
        "Привязка/отвязка — через веб-приложение, Settings → Telegram.",
        parse_mode="Markdown",
    )

@router.message(Command("today"))
async def cmd_today(msg):
    """Reply to /today with the user's events for the rest of the current day."""
    info = await _require_linked(msg)
    if info is None:
        return
    tz_name = info.get("timezone") or "UTC"
    start_iso, end_iso = isoformat_window(days_ahead=1, tz_name=tz_name)
    if msg.from_user is None:
        return
    try:
        events = await backend_client.list_events(
            msg.from_user.id, start_iso, end_iso, user_timezone=tz_name
        )
    except backend_client.BackendError as exc:
        await msg.answer(f"Не удалось получить календарь: {exc.message}")
        return
    await msg.answer(
        truncate_for_telegram(format_today(events, tz_name=tz_name)),
        parse_mode="Markdown",
    )

@router.message(Command("stats"))
async def cmd_stats(msg):
    """Reply to /stats with this week's per-category time-spent breakdown."""
    info = await _require_linked(msg)
    if info is None:
        return
    if msg.from_user is None:
        return
    try:
        stats = await backend_client.get_weekly_stats(
            msg.from_user.id, user_timezone=info.get("timezone") or "UTC"
        )
    except backend_client.BackendError as exc:
        await msg.answer(f"Не удалось получить статистику: {exc.message}")
        return
    await msg.answer(
        truncate_for_telegram(format_stats(stats)), parse_mode="Markdown"
    )
