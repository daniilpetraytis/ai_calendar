"""Speech-to-text helpers; currently a thin wrapper over Yandex SpeechKit v1."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_bot_settings

log = logging.getLogger(__name__)

YANDEX_STT_V1_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"

class STTError(Exception):
    """Raised on any speech-recognition failure (config, network, provider error)."""
    pass

@dataclass(slots=True)
class TranscriptionResult:
    """Successful transcription with the recognised text and which provider produced it."""
    text: str
    provider: str
    language: str

async def transcribe_voice(
    audio_bytes, *, mime_hint = "audio/ogg"
):
    """Transcribe a voice clip using the configured STT provider and return the result."""
    settings = get_bot_settings()
    if settings.stt_provider == "off":
        raise STTError("Голосовой ввод отключён (STT_PROVIDER=off).")

    if not audio_bytes:
        raise STTError("Пустой аудиофайл.")

    if settings.stt_provider == "yandex":
        return await _transcribe_yandex(audio_bytes, language=settings.stt_language)

    raise STTError(f"Unsupported STT_PROVIDER: {settings.stt_provider}")

async def _transcribe_yandex(audio_bytes, *, language):
    """Recognise speech via Yandex SpeechKit v1 (oggopus)."""
    settings = get_bot_settings()
    if not settings.yandex_api_key:
        raise STTError(
            "Голосовой ввод требует YANDEX_API_KEY в .env (он же используется бэкендом)."
        )
    if not settings.yandex_folder_id:
        raise STTError("Голосовой ввод требует YANDEX_FOLDER_ID в .env.")

    if len(audio_bytes) > 1024 * 1024:
        raise STTError("Голосовое слишком большое (> 1 MB). Запиши короче или напиши текстом.")

    params = {
        "folderId": settings.yandex_folder_id,
        "lang": language,
        "format": "oggopus",
        "profanityFilter": "false",
        "rawResults": "true",
    }
    headers = {
        "Authorization": f"Api-Key {settings.yandex_api_key}",
        "Content-Type": "audio/ogg",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                YANDEX_STT_V1_URL,
                params=params,
                headers=headers,
                content=audio_bytes,
            )
    except httpx.HTTPError as exc:
        log.warning("yandex stt network error: %s", exc)
        raise STTError(f"Сетевая ошибка SpeechKit: {exc}") from exc

    if resp.status_code != 200:
        body = resp.text[:300]
        log.warning("yandex stt %s: %s", resp.status_code, body)
        raise STTError(f"SpeechKit {resp.status_code}: {body}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise STTError(f"Bad SpeechKit response: {resp.text[:200]}") from exc

    text = (data.get("result") or "").strip()
    if not text:
        raise STTError("Не получилось распознать речь. Попробуй записать ещё раз чётче.")

    return TranscriptionResult(text=text, provider="yandex", language=language)
