"""Bot configuration (env-based)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class BotSettings(BaseSettings):
    """Runtime settings for the Telegram bot loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    telegram_bot_token: str = Field(default="", description="BotFather token")
    tg_bot_username: str = Field(default="", description="Bot username, without @")
    tg_bot_mode: Literal["polling", "webhook"] = "polling"
    tg_webhook_url: str = ""
    tg_webhook_secret: str = ""

    backend_url: str = "http://backend:8000"
    internal_service_token: str = Field(
        default="",
        description="Shared HMAC-style secret. Must equal backend's INTERNAL_SERVICE_TOKEN.",
    )

    push_listen_host: str = "0.0.0.0"
    push_listen_port: int = 8001

    log_level: str = "INFO"

    stt_provider: Literal["yandex", "off"] = "yandex"
    stt_language: str = "ru-RU"
    stt_max_voice_seconds: int = 30
    yandex_api_key: str = Field(default="")
    yandex_folder_id: str = Field(default="")

    stream_edit_throttle_ms: int = 900

    chat_stream_timeout_seconds: float = 120.0

@lru_cache(maxsize=1)
def get_bot_settings():
    """Return a process-wide cached `BotSettings` instance."""
    return BotSettings()
