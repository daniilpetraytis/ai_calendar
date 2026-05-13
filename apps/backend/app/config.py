"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Typed application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    encryption_key: str = Field(
        default="",
        description="Fernet key for encrypting OAuth tokens at rest.",
    )

    database_url: str = "postgresql+asyncpg://ai_calendar:ai_calendar@localhost:5432/ai_calendar"
    redis_url: str = "redis://localhost:6379/0"

    auth_provider: Literal["dev", "clerk"] = "dev"
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    clerk_secret_key: str = ""
    clerk_api_url: str = "https://api.clerk.com/v1"

    llm_provider: Literal["anthropic", "openai", "google", "openrouter", "yandex"] = "google"
    llm_model: str = "gemini-2.5-pro"
    classifier_model: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    openrouter_api_key: str = ""
    openai_base_url: str = ""
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_base_url: str = "https://llm.api.cloud.yandex.net/v1"
    yandex_disable_logging: bool = True

    llm_request_timeout_seconds: float = 30.0
    # Max LLM↔tool round-trips per agent run.
    agent_recursion_limit: int = 16
    # Hard wall-clock budget for one chat turn end-to-end.
    agent_total_timeout_seconds: float = 90.0

    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "http://localhost:8000/api/integrations/whoop/callback"
    # Space-separated. `offline` is mandatory for refresh tokens.
    whoop_scopes: str = (
        "offline read:recovery read:sleep read:workout read:cycles read:profile"
    )
    morning_push_min_local_hour: int = 7
    morning_push_max_local_hour: int = 11
    evening_prompt_after_last_event_minutes: int = 30
    evening_prompt_max_local_hour: int = 23
    evening_prompt_fallback_local_hour: int = 21
    whoop_workout_event_match_window_minutes: int = 60

    tg_bot_username: str = ""
    internal_service_token: str = ""
    tg_bot_push_url: str = ""
    # Lifetime of a connect deep-link before /exchange refuses it.
    telegram_link_ttl_minutes: int = 10

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    sentry_dsn: str = ""

    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def whoop_scopes_list(self):
        """Whoop OAuth scopes parsed from the space-separated string."""
        return [s.strip() for s in self.whoop_scopes.split() if s.strip()]

    @property
    def sync_database_url(self):
        """Synchronous SQLAlchemy URL derived from the async one (for Alembic, etc.)."""
        return self.database_url.replace("+asyncpg", "+psycopg2")

@lru_cache(maxsize=1)
def get_settings():
    """Return a process-wide cached `Settings` instance."""
    return Settings()
