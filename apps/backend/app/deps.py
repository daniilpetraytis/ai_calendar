"""Reusable FastAPI dependencies — current-user resolver, DB session, etc."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthPrincipal, get_principal
from app.auth.users import resolve_or_create_user
from app.db import get_session
from app.db.models import User

async def get_current_user(
    principal: Annotated[AuthPrincipal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    user_timezone: Annotated[str | None, Header(alias="X-User-Timezone")] = None,
) -> User:
    """Resolve the authenticated principal to a `User`, creating one on first sight."""
    return await resolve_or_create_user(session, principal, timezone=user_timezone)

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
