"""Internal FastAPI push endpoint that lets the backend send Telegram messages via the bot.

The backend POSTs to /push with an internal-service token and the bot relays the message
(optionally with an inline keyboard) to the target Telegram user.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from aiogram import Bot
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_bot_settings

log = logging.getLogger(__name__)

class PushPayload(BaseModel):
    """Body of an internal /push request: target user, text, and optional keyboard."""

    telegram_user_id: int = Field(..., gt=0)
    user_id: str | None = None
    text: str
    parse_mode: str | None = None
    keyboard: list[list[dict[str, str]]] | None = None

def build_push_app(bot: Bot) -> FastAPI:
    """Build the FastAPI app exposing /health and /push for backend-initiated messages."""
    app = FastAPI(title="tg-bot push receiver", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Lightweight liveness probe."""
        return {"status": "ok"}

    @app.post("/push")
    async def push(
        payload: PushPayload,
        x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
    ) -> dict[str, Any]:
        """Send a message to a Telegram user on behalf of the backend."""
        settings = get_bot_settings()
        if not settings.internal_service_token:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "INTERNAL_SERVICE_TOKEN is not configured on the bot.",
            )
        if not x_internal_token or not secrets.compare_digest(
            x_internal_token, settings.internal_service_token
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token")

        reply_markup = None
        if payload.keyboard:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=btn.get("text", "•"),
                            callback_data=btn.get("callback_data") or "noop",
                        )
                        for btn in row
                    ]
                    for row in payload.keyboard
                ]
            )

        try:
            sent = await bot.send_message(
                payload.telegram_user_id,
                payload.text,
                parse_mode=payload.parse_mode,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            log.warning("push send failed: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Telegram rejected: {exc}"
            ) from exc

        return {"ok": True, "message_id": sent.message_id}

    return app
