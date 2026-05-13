"""Free-form text chat router: streams agent replies and surfaces re-plan proposals."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app import backend_client, state
from app.config import get_bot_settings
from app.formatting import format_proposal, truncate_for_telegram
from app.handlers.commands import _require_linked

log = logging.getLogger(__name__)

router = Router(name="chat")

def _thread_id_for_chat(message):
    """Build a stable agent-thread identifier from the Telegram chat id."""
    return f"tg-{message.chat.id}"

class StreamingMessage:
    """Telegram message wrapper that throttles edits while streaming agent tokens."""

    def __init__(self, placeholder, *, throttle_ms):
        self._msg = placeholder
        self._throttle = throttle_ms / 1000.0
        self._buffer = []
        self._last_edit_at = 0.0
        self._last_rendered = ""

    def append(self, text):
        """Append a streamed token chunk to the in-memory buffer."""
        if text:
            self._buffer.append(text)

    @property
    def text(self):
        """Concatenated text currently in the buffer."""
        return "".join(self._buffer)

    async def maybe_edit(self):
        """Edit the Telegram message only if enough time has passed since the last edit."""
        now = time.monotonic()
        if now - self._last_edit_at < self._throttle:
            return
        await self._do_edit()

    async def flush(self):
        """Force a final edit, ignoring the throttle."""
        await self._do_edit(force=True)

    async def replace(self, new_text, *, parse_mode = None):
        """Replace the buffer with `new_text` and immediately push it to Telegram."""
        self._buffer = [new_text]
        await self._do_edit(force=True, parse_mode=parse_mode)

    async def _do_edit(self, *, force = False, parse_mode = None):
        """Push the current buffer to Telegram, swallowing rate-limit and rejection errors."""
        text = self.text
        if not text:
            return
        text = truncate_for_telegram(text)
        if text == self._last_rendered:
            self._last_edit_at = time.monotonic()
            return
        try:
            await self._msg.edit_text(text, parse_mode=parse_mode)
            self._last_rendered = text
            self._last_edit_at = time.monotonic()
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.1)
            if not force:
                return
            try:
                await self._msg.edit_text(text, parse_mode=parse_mode)
                self._last_rendered = text
                self._last_edit_at = time.monotonic()
            except TelegramBadRequest:
                pass
        except TelegramBadRequest as exc:
            log.debug("telegram edit rejected: %s", exc)

def _apply_keyboard(run_id):
    """Build the Apply / Reject inline keyboard for a proposal."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Применить", callback_data=f"apply:{run_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{run_id}"),
            ]
        ]
    )

async def run_chat_turn(
    msg,
    *,
    text,
    info,
    placeholder = None,
):
    """Run one streaming chat turn against the backend and render output to Telegram.

    Streams agent tokens into a placeholder message, surfaces tool activity hints,
    handles errors, and posts a separate proposal card with Apply/Reject buttons
    if the run produced one.
    """
    if msg.from_user is None:
        return
    tz_name = info.get("timezone") or "UTC"
    settings = get_bot_settings()

    await msg.bot.send_chat_action(msg.chat.id, "typing")
    if placeholder is None:
        placeholder = await msg.answer("…")
    streamer = StreamingMessage(
        placeholder, throttle_ms=settings.stream_edit_throttle_ms
    )

    proposal_seen = None
    proposal_run_id = None
    saw_token = False
    last_event_at = time.monotonic()

    try:
        async for event_name, payload in backend_client.stream_chat(
            msg.from_user.id,
            text,
            thread_id=_thread_id_for_chat(msg),
            user_timezone=tz_name,
        ):
            last_event_at = time.monotonic()
            if event_name == "token":
                streamer.append(payload.get("text", ""))
                saw_token = True
                await streamer.maybe_edit()
            elif event_name == "tool_start":
                # Show subtle activity hint while a tool runs.
                name = payload.get("name") or "tool"
                if not saw_token:
                    await streamer.replace(f"⚙️ {name}…")
            elif event_name == "tool_end":
                # Re-establish typing so the user knows we're still moving.
                with contextlib.suppress(Exception):
                    await msg.bot.send_chat_action(msg.chat.id, "typing")
            elif event_name == "proposal":
                proposal_seen = payload.get("proposal")
                proposal_run_id = payload.get("run_id")
            elif event_name == "final":
                final_text = (payload.get("message") or "").strip()
                if final_text:
                    await streamer.replace(final_text)
                elif not saw_token:
                    await streamer.replace("✓")
                else:
                    await streamer.flush()
            elif event_name == "error":
                error_text = payload.get("message") or "Что-то пошло не так."
                await streamer.replace(f"⚠️ {error_text}")
                return
            else:
                # run_started / unknown — silently consumed.
                pass

            if time.monotonic() - last_event_at > settings.chat_stream_timeout_seconds:
                await streamer.replace("⏱️ Backend замолчал, попробуй ещё раз.")
                return
    except Exception as exc:
        log.exception("chat stream failed")
        await streamer.replace(f"⚠️ Сбой стрима: {exc}")
        return
    finally:
        # Ensure the placeholder doesn't stay as "…"
        if not streamer.text:
            await streamer.replace("✓")

    if proposal_seen and proposal_run_id:
        await msg.answer(
            format_proposal(proposal_seen, tz_name=tz_name),
            parse_mode="Markdown",
            reply_markup=_apply_keyboard(proposal_run_id),
        )

@router.message(F.text & ~F.text.startswith("/"))
async def handle_chat_message(msg):
    """Handle any non-command text message: route to evening-feedback flow or chat agent."""
    info = await _require_linked(msg)
    if info is None:
        return

    if msg.from_user is not None and await state.is_awaiting_evening_text(
        msg.from_user.id
    ):
        score = await state.consume_awaiting_evening_text(msg.from_user.id)
        text = (msg.text or "").strip()
        try:
            await backend_client.post_evening_feedback(
                msg.from_user.id, score=score or 2, text=text or None
            )
            await msg.answer("Записал, спасибо 🙏")
        except backend_client.BackendError as exc:
            await msg.answer(f"Не получилось сохранить фидбек: {exc.message}")
        return

    await run_chat_turn(msg, text=msg.text or "", info=info)
