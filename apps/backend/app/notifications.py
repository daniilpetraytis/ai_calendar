"""Push notification dispatcher — currently routes to the Telegram bot."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings
from app.db.models import User

log = logging.getLogger(__name__)

async def push_to_user(
    user,
    text,
    *,
    keyboard = None,
    parse_mode = None,
):
    """Send a push message to the given user via the Telegram bot service.

    Returns `True` on successful delivery and `False` if the user has no
    Telegram link, the bot is not configured, or the HTTP call fails.
    """
    settings = get_settings()
    if not settings.tg_bot_push_url or not settings.internal_service_token:
        return False
    if user.telegram_user_id is None:
        return False

    payload = {
        "user_id": str(user.id),
        "telegram_user_id": user.telegram_user_id,
        "text": text,
    }
    if keyboard is not None:
        payload["keyboard"] = keyboard
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode

    url = settings.tg_bot_push_url.rstrip("/") + "/push"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Internal-Token": settings.internal_service_token},
            )
        if resp.status_code >= 300:
            log.warning(
                "tg-bot push rejected",
                extra={
                    "user_id": str(user.id),
                    "status": resp.status_code,
                    "body": resp.text[:200],
                },
            )
            return False
        return True
    except Exception as exc:
        log.warning(
            "tg-bot push failed", extra={"user_id": str(user.id), "error": str(exc)}
        )
        return False

async def push_to_user_id(
    user_id,
    text,
    *,
    keyboard = None,
    parse_mode = None,
    session=None,
):
    """Look up a user by id and dispatch a push, opening a session if not provided."""
    if session is None:
        from app.db import get_sessionmaker

        sm = get_sessionmaker()
        async with sm() as s:
            user = await s.get(User, user_id)
            if user is None:
                return False
            return await push_to_user(user, text, keyboard=keyboard, parse_mode=parse_mode)
    user = await session.get(User, user_id)
    if user is None:
        return False
    return await push_to_user(user, text, keyboard=keyboard, parse_mode=parse_mode)
