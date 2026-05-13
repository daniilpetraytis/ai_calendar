"""SQLAlchemy async engine, session, and declarative base."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    """Declarative base for all ORM models with a shared metadata naming convention."""
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

class TimestampMixin:
    """Mixin adding ``created_at`` and ``updated_at`` columns managed by the database."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

class UUIDPKMixin:
    """Mixin providing a UUID primary key column with a Python-side default."""
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )

_engine = None
sessionmaker_async: async_sessionmaker[AsyncSession] | None = None

def get_engine():
    """Return the lazily-initialized async SQLAlchemy engine, creating it on first use."""
    global _engine, sessionmaker_async
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            echo=False,
        )
        sessionmaker_async = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine

def get_sessionmaker():
    """Return the configured async session factory, initializing the engine if needed."""
    get_engine()
    assert sessionmaker_async is not None
    return sessionmaker_async

async def get_session():
    """FastAPI-style dependency yielding an ``AsyncSession`` with commit/rollback handling."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
