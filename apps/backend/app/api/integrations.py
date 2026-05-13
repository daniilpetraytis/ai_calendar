"""OAuth flows for external integrations."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, select

from app.api.schemas import YandexConnectRequest
from app.biometrics import service as biometrics_service
from app.biometrics import whoop as whoop_sdk
from app.calendar.caldav import (
    YANDEX_CALDAV_URL,
    AuthorizationError,
    CalDAVClient,
    yandex_auth,
)
from app.calendar.service import (
    get_yandex_integration,
    sync_from_yandex,
)
from app.config import get_settings
from app.db.models import (
    Integration,
    IntegrationProvider,
    TelegramLinkToken,
    User,
)
from app.deps import CurrentUser, DbSession
from app.security import encrypt

router = APIRouter()

_OAUTH_STATE: dict[str, str] = {}

@router.get("/status")
async def integrations_status(
    user: CurrentUser, session: DbSession
) -> dict[str, dict]:
    """Return connection status for each external integration provider."""
    rows = (
        await session.execute(
            select(Integration).where(Integration.user_id == user.id)
        )
    ).scalars().all()
    out: dict[str, dict] = {p.value: {"connected": False} for p in IntegrationProvider}
    for r in rows:
        out[r.provider.value] = {
            "connected": True,
            "account_email": r.account_email,
            "scopes": r.scopes,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        }
    out["telegram"] = {
        "connected": user.telegram_user_id is not None,
        "telegram_user_id": user.telegram_user_id,
    }
    return out

@router.post("/yandex/connect")
async def yandex_connect(
    payload: YandexConnectRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, object]:
    """Connect the user's Yandex CalDAV account and run an initial sync."""
    auth = yandex_auth(payload.email, payload.app_password)
    client = CalDAVClient(auth=auth)
    try:
        calendar_url = await client.discover()
    except AuthorizationError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Не удалось войти в Яндекс CalDAV. Проверьте email и пароль приложения "
            "(https://id.yandex.ru/security/app-passwords).",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Не удалось подключиться к Яндекс CalDAV: {exc}",
        ) from exc

    existing = await get_yandex_integration(session, user)
    sync_state = {
        "base_url": YANDEX_CALDAV_URL,
        "calendar_url": calendar_url,
    }
    if existing is None:
        existing = Integration(
            tenant_id=user.tenant_id,
            user_id=user.id,
            provider=IntegrationProvider.YANDEX_CALENDAR,
            access_token_enc=encrypt(payload.app_password),
            refresh_token_enc=None,
            expires_at=None,
            scopes="caldav",
            account_email=payload.email,
            sync_state=sync_state,
        )
        session.add(existing)
    else:
        existing.access_token_enc = encrypt(payload.app_password)
        existing.account_email = payload.email
        existing.sync_state = sync_state

    await session.flush()

    try:
        await sync_from_yandex(session, user, full=True)
    except Exception as exc:  # don't fail the connect if sync hiccups
        return {"ok": True, "calendar_url": calendar_url, "sync_warning": str(exc)}

    return {"ok": True, "calendar_url": calendar_url}

@router.delete("/yandex")
async def yandex_disconnect(user: CurrentUser, session: DbSession) -> dict[str, bool]:
    """Disconnect the user's Yandex CalDAV integration."""
    integration = await get_yandex_integration(session, user)
    if integration is not None:
        await session.delete(integration)
    return {"ok": True}

@router.get("/whoop/connect")
async def whoop_connect(user: CurrentUser) -> dict[str, str]:
    """Issue a Whoop OAuth authorize URL bound to a fresh state token."""
    state = secrets.token_urlsafe(24)
    _OAUTH_STATE[state] = str(user.id)
    return {"authorize_url": whoop_sdk.build_authorize_url(state)}

@router.get("/whoop/callback")
async def whoop_callback(
    session: DbSession,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Handle the Whoop OAuth callback, store tokens and redirect back to the app."""
    settings = get_settings()
    redirect_base = settings.cors_origins[0] + "/settings"

    if error or not code:
        msg = error_description or error or "missing_code"
        params = urlencode({"whoop_error": msg[:500]})
        return RedirectResponse(f"{redirect_base}?{params}", status_code=302)

    if not state:
        params = urlencode({"whoop_error": "missing_state"})
        return RedirectResponse(f"{redirect_base}?{params}", status_code=302)

    user_id = _OAUTH_STATE.pop(state, None)
    if user_id is None:
        params = urlencode({"whoop_error": "invalid_or_expired_state"})
        return RedirectResponse(f"{redirect_base}?{params}", status_code=302)

    user = await session.get(User, user_id)
    if user is None:
        params = urlencode({"whoop_error": "user_not_found"})
        return RedirectResponse(f"{redirect_base}?{params}", status_code=302)

    try:
        token = await whoop_sdk.exchange_code(code)
    except Exception as exc:  # noqa: BLE001
        params = urlencode({"whoop_error": f"token_exchange_failed: {exc}"[:500]})
        return RedirectResponse(f"{redirect_base}?{params}", status_code=302)

    existing = (
        await session.execute(
            select(Integration).where(
                and_(
                    Integration.user_id == user.id,
                    Integration.provider == IntegrationProvider.WHOOP,
                )
            )
        )
    ).scalar_one_or_none()

    sync_state = {}
    if token.user_id:
        sync_state["whoop_user_id"] = token.user_id

    if existing is None:
        existing = Integration(
            tenant_id=user.tenant_id,
            user_id=user.id,
            provider=IntegrationProvider.WHOOP,
            access_token_enc=encrypt(token.access_token),
            refresh_token_enc=encrypt(token.refresh_token) if token.refresh_token else None,
            expires_at=token.expires_at,
            scopes=token.scope,
            account_email=token.account_email,
            sync_state=sync_state,
        )
        session.add(existing)
    else:
        existing.access_token_enc = encrypt(token.access_token)
        if token.refresh_token:
            existing.refresh_token_enc = encrypt(token.refresh_token)
        existing.expires_at = token.expires_at
        existing.scopes = token.scope
        existing.account_email = token.account_email or existing.account_email
        merged_state = dict(existing.sync_state or {})
        merged_state.update(sync_state)
        existing.sync_state = merged_state

    await session.flush()

    try:
        await biometrics_service.sync_from_whoop(session, user, days_back=30)
    except Exception as exc:
        merged_state = dict(existing.sync_state or {})
        merged_state["last_sync_error"] = str(exc)[:500]
        existing.sync_state = merged_state

    redirect_target = f"{settings.cors_origins[0]}/settings?connected=whoop"
    return RedirectResponse(redirect_target, status_code=302)

@router.delete("/whoop")
async def whoop_disconnect(user: CurrentUser, session: DbSession) -> dict[str, bool]:
    """Disconnect the user's Whoop integration and drop stored tokens."""
    integration = await biometrics_service.get_whoop_integration(session, user)
    if integration is not None:
        await session.delete(integration)
    return {"ok": True}

def _require_internal_token(token: str | None) -> None:
    """Validate the shared service-to-service token used by internal callers."""
    settings = get_settings()
    if not settings.internal_service_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "INTERNAL_SERVICE_TOKEN is not configured on the backend.",
        )
    if not token or not secrets.compare_digest(token, settings.internal_service_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token")

class TelegramExchangeRequest(BaseModel):
    """Internal request from the Telegram bot exchanging a link token for a user."""

    token: str = Field(..., min_length=8, max_length=64)
    telegram_user_id: int = Field(..., gt=0)
    telegram_username: str | None = None

class TelegramLookupRequest(BaseModel):
    """Internal request to look up a user by their Telegram user id."""

    telegram_user_id: int = Field(..., gt=0)

@router.post("/telegram/connect")
async def telegram_connect(
    user: CurrentUser, session: DbSession
) -> dict[str, str]:
    """Issue a one-time deep link to link the user with the Telegram bot."""
    settings = get_settings()
    if not settings.tg_bot_username:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TG_BOT_USERNAME is not configured on the backend.",
        )

    token = secrets.token_urlsafe(24)
    session.add(
        TelegramLinkToken(
            token=token,
            tenant_id=user.tenant_id,
            user_id=user.id,
            expires_at=datetime.now(UTC)
            + timedelta(minutes=settings.telegram_link_ttl_minutes),
        )
    )
    await session.flush()
    return {
        "deeplink": f"https://t.me/{settings.tg_bot_username}?start={token}",
        "expires_in_minutes": str(settings.telegram_link_ttl_minutes),
    }

@router.post("/telegram/exchange")
async def telegram_exchange(
    payload: TelegramExchangeRequest,
    session: DbSession,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> dict[str, object]:
    """Bind a Telegram account to the user identified by the link token."""
    _require_internal_token(x_internal_token)

    link = await session.get(TelegramLinkToken, payload.token)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown link token")
    if link.used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Link token already used")
    if link.expires_at <= datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "Link token has expired")

    user = await session.get(User, link.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User vanished")

    existing = (
        await session.execute(
            select(User).where(User.telegram_user_id == payload.telegram_user_id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.id != user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Telegram account is already linked to a different user.",
        )

    user.telegram_user_id = payload.telegram_user_id
    link.used = True
    link.used_at = datetime.now(UTC)
    return {
        "ok": True,
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "timezone": user.timezone,
    }

@router.post("/telegram/lookup")
async def telegram_lookup(
    payload: TelegramLookupRequest,
    session: DbSession,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> dict[str, object]:
    """Look up an existing user already linked to the given Telegram id."""
    _require_internal_token(x_internal_token)
    user = (
        await session.execute(
            select(User).where(User.telegram_user_id == payload.telegram_user_id)
        )
    ).scalar_one_or_none()
    if user is None:
        return {"linked": False}
    return {
        "linked": True,
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "timezone": user.timezone,
    }

@router.delete("/telegram")
async def telegram_disconnect(user: CurrentUser) -> dict[str, bool]:
    """Unlink the user's Telegram account."""
    user.telegram_user_id = None
    return {"ok": True}
