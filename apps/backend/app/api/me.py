"""Current-user profile and onboarding endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import CurrentUser, DbSession

router = APIRouter()

class MeOut(BaseModel):
    """Profile snapshot returned by the ``/me`` endpoints."""

    id: str
    email: str
    display_name: str | None
    timezone: str
    onboarded_at: datetime | None

@router.get("", response_model=MeOut)
async def get_me(user: CurrentUser) -> MeOut:
    """Return the authenticated user's profile."""
    return MeOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        timezone=user.timezone,
        onboarded_at=user.onboarded_at,
    )

@router.post("/onboarding/complete", response_model=MeOut)
async def complete_onboarding(
    user: CurrentUser, session: DbSession
) -> MeOut:
    """Mark the user as having completed onboarding (idempotent)."""
    if user.onboarded_at is None:
        user.onboarded_at = datetime.now(UTC)
        await session.flush()
    return MeOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        timezone=user.timezone,
        onboarded_at=user.onboarded_at,
    )
