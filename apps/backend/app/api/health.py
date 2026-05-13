"""Liveness/readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.deps import DbSession

router = APIRouter()

@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — returns ok if the process is responsive."""
    return {"status": "ok"}

@router.get("/readyz")
async def readyz(session: DbSession) -> dict[str, str]:
    """Readiness probe — verifies the database is reachable."""
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
