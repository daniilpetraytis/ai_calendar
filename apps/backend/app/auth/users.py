"""Reusable user resolution: principal -> DB User (auto-provisioning)."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.providers import AuthPrincipal
from app.db.models import Tenant, User

async def resolve_or_create_user(
    session,
    principal,
    *,
    timezone = None,
):
    """Find the ``User`` for ``principal`` or auto-provision one (with a fresh tenant).

    Matching order is: linked Telegram id, then external auth id, then email
    (back-filling the missing external id). Updates the stored timezone in place
    when a new value is supplied."""

    def _maybe_set_tz(u):
        if timezone and u.timezone != timezone:
            u.timezone = timezone

    if principal.telegram_user_id is not None:
        user = (
            await session.execute(
                select(User).where(User.telegram_user_id == principal.telegram_user_id)
            )
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Telegram account is not linked to any user. "
                "Open the web app /settings → Telegram → Connect.",
            )
        _maybe_set_tz(user)
        return user

    user = (
        await session.execute(
            select(User).where(User.external_auth_id == principal.external_id)
        )
    ).scalar_one_or_none()
    if user is not None:
        _maybe_set_tz(user)
        return user
    user = (
        await session.execute(select(User).where(User.email == principal.email))
    ).scalar_one_or_none()
    if user is not None:
        if not user.external_auth_id:
            user.external_auth_id = principal.external_id
        _maybe_set_tz(user)
        return user
    tenant = Tenant(name=principal.email)
    session.add(tenant)
    await session.flush()
    user = User(
        tenant_id=tenant.id,
        email=principal.email,
        display_name=principal.display_name,
        external_auth_id=principal.external_id,
        timezone=timezone or "UTC",
    )
    session.add(user)
    await session.flush()
    return user
