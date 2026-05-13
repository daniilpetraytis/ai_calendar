"""/start router: handles deep-link account linking and plain /start greetings."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from app import backend_client

log = logging.getLogger(__name__)

router = Router(name="start")

@router.message(CommandStart(deep_link=True))
async def cmd_start_with_token(msg, command):
    """Handle /start with a deep-link payload by exchanging the link token for an account."""
    token = (command.args or "").strip()
    if not token:
        await cmd_start_no_token(msg)
        return
    if msg.from_user is None:
        return
    try:
        info = await backend_client.exchange_link_token(
            token,
            telegram_user_id=msg.from_user.id,
            telegram_username=msg.from_user.username,
        )
    except backend_client.BackendError as exc:
        if exc.status_code in (404, 410):
            await msg.answer(
                "⌛ Ссылка истекла или уже использована. "
                "Сгенерируй новую: открой веб-приложение → Settings → Telegram → Connect."
            )
            return
        if exc.status_code == 409:
            await msg.answer(
                "🔁 Этот Telegram уже привязан к другому аккаунту. "
                "Отвяжи его в веб-приложении или используй ту учётку."
            )
            return
        log.exception("link exchange failed")
        await msg.answer(f"Не получилось привязать аккаунт: {exc.message}")
        return

    email = info.get("email") or ""
    name = info.get("display_name") or email or "👋"
    await msg.answer(
        f"Готово, {name}! Аккаунт привязан.\n\n"
        "Просто пиши, что нужно — поставить тренировку, перенести встречу, "
        "распланировать неделю. Команды: /today, /stats, /help."
    )

@router.message(CommandStart())
async def cmd_start_no_token(msg):
    """Handle a bare /start: greet linked users, or guide unlinked users to the web app."""
    if msg.from_user is None:
        return
    info = await backend_client.lookup_telegram_user(msg.from_user.id)
    if info is not None:
        name = info.get("display_name") or info.get("email") or "👋"
        await msg.answer(
            f"С возвращением, {name}!\n"
            "Пиши сообщением — я разрулю календарь. /today, /stats, /help."
        )
        return
    await msg.answer(
        "Привет! Я твой AI-календарь в Telegram.\n\n"
        "Сначала привяжи аккаунт:\n"
        "1. Открой веб-приложение → Settings → Telegram → Connect.\n"
        "2. Кликни на ссылку, она вернёт тебя сюда.\n\n"
        "После этого можно будет говорить со мной — «поставь тренировку завтра в 11», "
        "«что у меня сегодня», «распиши неделю»."
    )
