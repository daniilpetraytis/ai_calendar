"""Authentication providers — Clerk JWT, dev header, and Telegram internal-token — yielding a unified ``AuthPrincipal``."""

from __future__ import annotations

import secrets as _secrets
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx
from fastapi import Header, HTTPException, Request, status
from jose import JWTError, jwt

from app.config import get_settings

@dataclass(slots=True)
class AuthPrincipal:
    """Provider-agnostic identity resolved from an incoming request."""

    external_id: str
    email: str
    display_name: str | None = None
    telegram_user_id: int | None = None

async def _dev_principal(request):
    """Resolve the principal from the ``X-Dev-User-Email`` header; forbidden in production."""
    settings = get_settings()
    if settings.env == "production":
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Dev auth provider is forbidden in production. Set AUTH_PROVIDER=clerk.",
        )
    email = request.headers.get("x-dev-user-email")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Dev-User-Email header")
    return AuthPrincipal(external_id=f"dev:{email.lower()}", email=email.lower())

@lru_cache(maxsize=1)
def _http_client():
    return httpx.Client(timeout=5.0)

_jwks_cache: dict[str, tuple[float, dict]] = {}
_user_lookup_cache: dict[str, tuple[float, tuple[str, str | None]]] = {}

def _get_jwks(url):
    """Fetch and memoise the Clerk JWKS for ten minutes."""
    cached = _jwks_cache.get(url)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    resp = _http_client().get(url)
    resp.raise_for_status()
    data = resp.json()
    _jwks_cache[url] = (time.time(), data)
    return data

def _fetch_clerk_user(sub):
    """Look up a Clerk user via the Backend API, returning ``(email, display_name)`` with a ten-minute cache."""
    settings = get_settings()
    if not settings.clerk_secret_key:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "CLERK_SECRET_KEY is not configured. The Clerk session token does not "
            "include the user's email, so the backend needs the secret key to "
            "fetch it via the Clerk Backend API.",
        )
    cached = _user_lookup_cache.get(sub)
    if cached and time.time() - cached[0] < 600:
        return cached[1]

    url = f"{settings.clerk_api_url.rstrip('/')}/users/{sub}"
    try:
        resp = _http_client().get(
            url,
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Failed to resolve Clerk user {sub!r}: {exc}",
        ) from exc

    data = resp.json()
    primary_id = data.get("primary_email_address_id")
    email = None
    for entry in data.get("email_addresses") or []:
        if entry.get("id") == primary_id:
            email = entry.get("email_address")
            break
    if not email and data.get("email_addresses"):
        email = data["email_addresses"][0].get("email_address")
    if not email:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Clerk user {sub!r} has no email address.",
        )

    first = data.get("first_name") or ""
    last = data.get("last_name") or ""
    display_name = (f"{first} {last}".strip()) or data.get("username") or None

    value = (email.lower(), display_name)
    _user_lookup_cache[sub] = (time.time(), value)
    return value

async def _clerk_principal(authorization):
    """Verify the Clerk bearer JWT against the JWKS and resolve the principal."""
    settings = get_settings()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    if not settings.clerk_jwks_url:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "CLERK_JWKS_URL is not configured"
        )

    token = authorization.split(" ", 1)[1]
    try:
        jwks = _get_jwks(settings.clerk_jwks_url)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown signing key")
        claims = jwt.decode(
            token,
            key,
            algorithms=[unverified_header.get("alg", "RS256")],
            issuer=settings.clerk_issuer or None,
            options={"verify_aud": False},
        )
    except (JWTError, httpx.HTTPError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing sub")

    email = claims.get("email") or claims.get("primary_email_address") or ""
    name = claims.get("name") or claims.get("first_name")
    if not email:
        email, fetched_name = _fetch_clerk_user(sub)
        name = name or fetched_name
    return AuthPrincipal(
        external_id=f"clerk:{sub}", email=email.lower(), display_name=name
    )

async def _telegram_principal(
    request, internal_token, telegram_user_id_raw
):
    """Trust the Telegram bot's internal-token header and produce a principal carrying ``telegram_user_id``."""
    settings = get_settings()
    if not settings.internal_service_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "INTERNAL_SERVICE_TOKEN is not configured on the backend.",
        )
    if not _secrets.compare_digest(internal_token, settings.internal_service_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token")
    try:
        tg_id = int(telegram_user_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Bad X-Telegram-User-Id header"
        ) from exc
    if tg_id <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad X-Telegram-User-Id header")
    return AuthPrincipal(
        external_id=f"telegram:{tg_id}",
        email="",
        telegram_user_id=tg_id,
    )

async def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
    x_telegram_user_id: str | None = Header(default=None, alias="X-Telegram-User-Id"),
) -> AuthPrincipal:
    """FastAPI dependency that picks the right provider based on the request headers and current settings."""
    settings = get_settings()
    if x_internal_token and x_telegram_user_id:
        return await _telegram_principal(request, x_internal_token, x_telegram_user_id)
    if settings.auth_provider == "clerk":
        return await _clerk_principal(authorization)
    return await _dev_principal(request)
