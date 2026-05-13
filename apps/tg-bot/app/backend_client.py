"""HTTP client for the AI Calendar backend used by the Telegram bot.

Wraps internal-service-token-authenticated REST calls and SSE streaming for chat.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx
from httpx_sse import aconnect_sse

from app.config import get_bot_settings

log = logging.getLogger(__name__)

class BackendError(Exception):
    """Non-2xx response from the backend, carrying status code and detail message."""

    def __init__(self, status_code, message):
        super().__init__(f"backend {status_code}: {message}")
        self.status_code = status_code
        self.message = message

class NotLinkedError(BackendError):
    """Raised when the Telegram user is not linked to any backend account."""
    pass

def _user_headers(telegram_user_id, user_timezone = None):
    """Build internal-token headers identifying a specific Telegram user."""
    settings = get_bot_settings()
    headers = {
        "X-Internal-Token": settings.internal_service_token,
        "X-Telegram-User-Id": str(telegram_user_id),
    }
    if user_timezone:
        headers["X-User-Timezone"] = user_timezone
    return headers

def _internal_headers():
    """Build headers for backend endpoints that don't need a per-user identity."""
    settings = get_bot_settings()
    return {"X-Internal-Token": settings.internal_service_token}

@asynccontextmanager
async def _http_client():
    """Yield a configured async httpx client pointed at the backend base URL."""
    settings = get_bot_settings()
    async with httpx.AsyncClient(
        base_url=settings.backend_url, timeout=httpx.Timeout(30.0, connect=5.0)
    ) as client:
        yield client

def _check(resp):
    """Raise BackendError / NotLinkedError if the response is not 2xx."""
    if 200 <= resp.status_code < 300:
        return
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else str(body)
    except Exception:
        detail = resp.text
    if resp.status_code == 401 and "not linked" in str(detail).lower():
        raise NotLinkedError(resp.status_code, str(detail))
    raise BackendError(resp.status_code, str(detail))

async def exchange_link_token(
    token, telegram_user_id, telegram_username = None
):
    """Exchange a one-time link token for the linked backend user info."""
    async with _http_client() as c:
        resp = await c.post(
            "/api/integrations/telegram/exchange",
            json={
                "token": token,
                "telegram_user_id": telegram_user_id,
                "telegram_username": telegram_username,
            },
            headers=_internal_headers(),
        )
    _check(resp)
    return resp.json()

async def lookup_telegram_user(telegram_user_id):
    """Return the linked user's profile dict, or None if this Telegram user is not linked."""
    async with _http_client() as c:
        resp = await c.post(
            "/api/integrations/telegram/lookup",
            json={"telegram_user_id": telegram_user_id},
            headers=_internal_headers(),
        )
    _check(resp)
    data = resp.json()
    return data if data.get("linked") else None

async def list_events(
    telegram_user_id,
    start_iso,
    end_iso,
    *,
    user_timezone = None,
):
    """Fetch the user's calendar events between the given ISO timestamps."""
    async with _http_client() as c:
        resp = await c.get(
            "/api/events",
            params={"start": start_iso, "end": end_iso},
            headers=_user_headers(telegram_user_id, user_timezone),
        )
    _check(resp)
    return resp.json()

async def get_weekly_stats(
    telegram_user_id, *, user_timezone = None
):
    """Fetch the user's per-category time breakdown for the current week."""
    async with _http_client() as c:
        resp = await c.get(
            "/api/stats/by-category",
            params={"period": "week", "offset": 0},
            headers=_user_headers(telegram_user_id, user_timezone),
        )
    _check(resp)
    return resp.json()

async def post_evening_feedback(
    telegram_user_id,
    *,
    score,
    text = None,
):
    """Submit a 1–3 evening self-rating (and optional comment) for the current day."""
    body = {"score": score}
    if text:
        body["text"] = text
    async with _http_client() as c:
        resp = await c.post(
            "/api/biometrics/evening-feedback",
            json=body,
            headers=_user_headers(telegram_user_id),
        )
    _check(resp)
    return resp.json()

async def apply_proposal(
    telegram_user_id,
    run_id,
    *,
    approve,
    accepted_indices = None,
):
    """Approve or reject an agent re-plan proposal, optionally accepting a subset of changes."""
    body = {"approve": approve}
    if accepted_indices is not None:
        body["accepted_indices"] = accepted_indices
    async with _http_client() as c:
        resp = await c.post(
            f"/api/replan/{run_id}/apply",
            json=body,
            headers=_user_headers(telegram_user_id),
        )
    _check(resp)
    return resp.json()

async def stream_chat(
    telegram_user_id,
    message,
    *,
    thread_id = None,
    user_timezone = None,
):
    """Stream a chat turn from the backend as (event_name, payload) tuples over SSE.

    Yields parsed events such as ``token``, ``tool_start``, ``tool_end``, ``proposal``,
    ``final``, and ``error``. Network or HTTP failures surface as a final ``error`` event.
    """
    settings = get_bot_settings()
    headers = _user_headers(telegram_user_id, user_timezone)
    headers["Accept"] = "text/event-stream"

    body = {"message": message}
    if thread_id:
        body["thread_id"] = thread_id

    timeout = httpx.Timeout(settings.chat_stream_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(
        base_url=settings.backend_url, timeout=timeout
    ) as client:
        try:
            async with aconnect_sse(
                client, "POST", "/api/chat", json=body, headers=headers
            ) as event_source:
                resp = event_source.response
                if resp.status_code >= 300:
                    text = await resp.aread()
                    yield (
                        "error",
                        {"message": f"backend {resp.status_code}: {text.decode(errors='replace')[:200]}"},
                    )
                    return
                async for sse_event in event_source.aiter_sse():
                    name = sse_event.event or "message"
                    data = sse_event.data
                    if not data:
                        continue
                    try:
                        payload = json.loads(data)
                        if not isinstance(payload, dict):
                            payload = {"value": payload}
                    except json.JSONDecodeError:
                        payload = {"text": data}
                    yield name, payload
        except httpx.HTTPError as exc:
            yield "error", {"message": f"backend connection error: {exc}"}
