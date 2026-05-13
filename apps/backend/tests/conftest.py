"""Test fixtures: keep tests offline by stubbing settings before import."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

os.environ.setdefault("ENV", "development")
os.environ.setdefault("AUTH_PROVIDER", "dev")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
