"""Voice-message router: downloads the audio, runs STT, then forwards to the chat agent."""

from __future__ import annotations

import io
import logging

from aiogram import F, Router
from aiogram.types import Message

from app.config import get_bot_settings
from app.handlers.chat import run_chat_turn
from app.handlers.commands import _require_linked
from app.stt import STTError, transcribe_voice

log = logging.getLogger(__name__)

router = Router(name="voice")

def _format_transcript_header(transcript):
    """Build the "распознано: …" preview header for the recognised transcript."""
    snippet = transcript.replace("\n", " ").strip()
    if len(snippet) > 300:
        snippet = snippet[:299] + "…"
    return f"_📝 распознано:_ {snippet}"

@router.message(F.voice)
async def handle_voice(msg):
    """Handle an incoming voice note: validate, transcribe, and run a chat turn on the result."""
    info = await _require_linked(msg)
    if info is None:
        return
    if msg.voice is None or msg.from_user is None:
        return

    settings = get_bot_settings()
    if settings.stt_provider == "off":
        await msg.answer(
            "Голосовые сейчас отключены. Напиши текстом или включи STT_PROVIDER в .env."
        )
        return

    duration = msg.voice.duration or 0
    if duration > settings.stt_max_voice_seconds:
        await msg.answer(
            f"Голосовое длиннее {settings.stt_max_voice_seconds} с — "
            "Yandex SpeechKit v1 такие не принимает. Запиши короче или напиши текстом."
        )
        return

    placeholder = await msg.answer("🎙️ распознаю…")

    buf = io.BytesIO()
    try:
        await msg.bot.download(msg.voice, destination=buf)
    except Exception as exc:
        log.exception("voice download failed")
        await placeholder.edit_text(f"⚠️ Не удалось скачать аудио: {exc}")
        return
    audio_bytes = buf.getvalue()

    try:
        result = await transcribe_voice(audio_bytes, mime_hint=msg.voice.mime_type or "audio/ogg")
    except STTError as exc:
        await placeholder.edit_text(f"⚠️ {exc}")
        return
    except Exception as exc:
        log.exception("STT crashed")
        await placeholder.edit_text(f"⚠️ Сбой распознавания: {exc}")
        return

    header = _format_transcript_header(result.text)
    try:
        await placeholder.edit_text(header, parse_mode="Markdown")
    except Exception:
        await placeholder.edit_text(header)

    await run_chat_turn(msg, text=result.text, info=info, placeholder=None)
