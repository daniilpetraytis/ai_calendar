"""Calendar service layer — orchestrates the local ``Event`` model with the CalDAV remote (currently Yandex)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar.caldav import (
    CalDAVAuth,
    CalDAVClient,
    CalDAVEvent,
)
from app.categorize.service import classify_event_by_rules
from app.db.models import Event, EventSource, Integration, IntegrationProvider, User
from app.security import decrypt

log = logging.getLogger(__name__)

class IntegrationNotConnected(RuntimeError):
    """Raised when a sync operation runs without a connected calendar integration."""

    pass

async def get_integration(
    session, user, provider
):
    """Return the ``Integration`` row for ``(user, provider)`` or ``None``."""
    return (
        await session.execute(
            select(Integration).where(
                and_(Integration.user_id == user.id, Integration.provider == provider)
            )
        )
    ).scalar_one_or_none()

async def get_yandex_integration(session, user):
    """Shortcut for the Yandex Calendar integration row."""
    return await get_integration(session, user, IntegrationProvider.YANDEX_CALENDAR)

async def get_active_calendar_integration(
    session, user
):
    """Return whichever calendar integration is currently the user's active one (today: Yandex only)."""
    return await get_yandex_integration(session, user)

def _caldav_auth_from_integration(integration):
    """Decrypt the stored password and assemble a ``CalDAVAuth`` from the integration row."""
    password = decrypt(integration.access_token_enc)
    sync_state = integration.sync_state or {}
    base_url = sync_state.get("base_url") or "https://caldav.yandex.ru"
    return CalDAVAuth(url=base_url, username=integration.account_email or "", password=password)

async def get_caldav_client(
    session, user, *, provider
):
    """Build a ``CalDAVClient`` for the given provider, reusing the cached calendar URL when known."""
    integration = await get_integration(session, user, provider)
    if integration is None:
        return None
    auth = _caldav_auth_from_integration(integration)
    sync_state = integration.sync_state or {}
    return CalDAVClient(auth=auth, calendar_url=sync_state.get("calendar_url"))

async def _upsert_remote_event(
    session,
    user,
    *,
    source,
    external_id,
    calendar_id,
    title,
    description,
    location,
    start_at,
    end_at,
    all_day,
    etag,
    extra = None,
):
    """Insert or update a remote-sourced ``Event``, re-running the rule categoriser when the user hasn't overridden it."""
    existing = (
        await session.execute(
            select(Event).where(
                and_(
                    Event.user_id == user.id,
                    Event.source == source,
                    Event.external_id == external_id,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = Event(
            tenant_id=user.tenant_id,
            user_id=user.id,
            source=source,
            external_id=external_id,
            calendar_id=calendar_id,
        )
        session.add(existing)
    existing.title = title
    existing.description = description
    existing.location = location
    existing.start_at = start_at
    existing.end_at = end_at
    existing.all_day = all_day
    existing.etag = etag
    if extra is not None:
        existing.extra = extra

    if existing.category_source != "user":
        classify_event_by_rules(existing)

    return existing

async def upsert_event_from_caldav(
    session, user, calendar_url, ce
):
    """Project a single ``CalDAVEvent`` into a local ``Event`` row, keyed by its iCal UID."""
    return await _upsert_remote_event(
        session,
        user,
        source=EventSource.YANDEX,
        external_id=ce.uid,
        calendar_id=calendar_url,
        title=ce.summary,
        description=ce.description,
        location=ce.location,
        start_at=ce.start,
        end_at=ce.end,
        all_day=ce.all_day,
        etag=ce.etag,
        extra={"caldav": {"raw": ce.raw_ical}},
    )

async def sync_from_yandex(session, user, *, full = False):
    """Pull events from Yandex Calendar for a window around today and upsert them locally.

    Uses the stored CTag to short-circuit when nothing has changed unless ``full`` forces a full pass."""
    integration = await get_yandex_integration(session, user)
    if integration is None:
        raise IntegrationNotConnected("Yandex Calendar is not connected")

    auth = _caldav_auth_from_integration(integration)
    sync_state = dict(integration.sync_state or {})
    client = CalDAVClient(auth=auth, calendar_url=sync_state.get("calendar_url"))
    new_ctag = await client.get_ctag()
    if not full and new_ctag and new_ctag == sync_state.get("ctag"):
        return 0

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = now + timedelta(days=90)
    events = await client.list_events(time_min=time_min, time_max=time_max)
    calendar_url = sync_state.get("calendar_url") or await client.discover()
    count = 0
    for ev in events:
        await upsert_event_from_caldav(session, user, calendar_url, ev)
        count += 1

    sync_state["calendar_url"] = calendar_url
    if new_ctag:
        sync_state["ctag"] = new_ctag
    sync_state["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    integration.sync_state = sync_state
    return count

async def sync_user_calendar(session, user, *, full = False):
    """Sync the user's currently active calendar integration; no-op when none is connected."""
    integration = await get_active_calendar_integration(session, user)
    if integration is None:
        return 0
    if integration.provider == IntegrationProvider.YANDEX_CALENDAR:
        return await sync_from_yandex(session, user, full=full)
    return 0

async def list_events(
    session,
    user,
    *,
    start,
    end,
):
    """Return the user's events whose interval intersects ``[start, end)`` ordered by start time."""
    rows = await session.execute(
        select(Event)
        .where(
            and_(
                Event.user_id == user.id,
                Event.end_at > start,
                Event.start_at < end,
            )
        )
        .order_by(Event.start_at.asc())
    )
    return list(rows.scalars().all())

async def create_event(
    session,
    user,
    *,
    title,
    start,
    end,
    description = None,
    location = None,
    is_movable = True,
    priority = 0,
):
    """Create a local event and mirror it to the active calendar integration when one is connected."""
    integration = await get_active_calendar_integration(session, user)
    event = Event(
        tenant_id=user.tenant_id,
        user_id=user.id,
        title=title,
        description=description,
        location=location,
        start_at=start,
        end_at=end,
        is_movable=is_movable,
        priority=priority,
        source=EventSource.LOCAL,
    )
    if integration is not None and integration.provider == IntegrationProvider.YANDEX_CALENDAR:
        cclient = await get_caldav_client(
            session, user, provider=IntegrationProvider.YANDEX_CALENDAR
        )
        if cclient is not None:
            ce = await cclient.create_event(
                title=title,
                start=start,
                end=end,
                description=description,
                location=location,
            )
            event.source = EventSource.YANDEX
            event.external_id = ce.uid
            event.calendar_id = (integration.sync_state or {}).get("calendar_url")
            event.etag = ce.etag
    classify_event_by_rules(event)

    session.add(event)
    await session.flush()
    return event

async def _patch_remote(
    session,
    user,
    event,
    *,
    title = None,
    description = None,
    location = None,
    start = None,
    end = None,
):
    """Forward the supplied field changes to the linked CalDAV server and update the cached etag."""
    if not event.external_id:
        return
    if event.source == EventSource.YANDEX:
        cclient = await get_caldav_client(
            session, user, provider=IntegrationProvider.YANDEX_CALENDAR
        )
        if cclient is not None:
            ce = await cclient.patch_event(
                event.external_id,
                title=title,
                description=description,
                location=location,
                start=start,
                end=end,
            )
            event.etag = ce.etag

async def move_event(
    session,
    user,
    *,
    event_id,
    new_start,
    new_end,
):
    """Reschedule a local event and push the new times to the remote calendar."""
    event = await session.get(Event, event_id)
    if event is None or event.user_id != user.id:
        raise ValueError(f"event {event_id} not found")
    event.start_at = new_start
    event.end_at = new_end
    await _patch_remote(session, user, event, start=new_start, end=new_end)
    return event

async def update_event(
    session,
    user,
    *,
    event_id,
    title = None,
    description = None,
    location = None,
):
    """Patch local event metadata (title / description / location) and mirror it to the remote calendar."""
    event = await session.get(Event, event_id)
    if event is None or event.user_id != user.id:
        raise ValueError(f"event {event_id} not found")
    if title is not None:
        event.title = title
    if description is not None:
        event.description = description
    if location is not None:
        event.location = location
    await _patch_remote(
        session, user, event, title=title, description=description, location=location
    )
    return event

async def delete_event(session, user, *, event_id):
    """Delete a local event and best-effort remove its CalDAV counterpart when linked."""
    event = await session.get(Event, event_id)
    if event is None or event.user_id != user.id:
        return
    if event.external_id and event.source == EventSource.YANDEX:
        cclient = await get_caldav_client(
            session, user, provider=IntegrationProvider.YANDEX_CALENDAR
        )
        if cclient is not None:
            await cclient.delete_event(event.external_id)
    await session.delete(event)
