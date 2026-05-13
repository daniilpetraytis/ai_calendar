"""CRUD for user places, Yandex.Maps route URL building, and route note formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, Place, User

DEFAULT_ROUTE_MODE: str = "mt"  # public transport

_VALID_MODES = frozenset({"mt", "auto", "pd", "bc"})

def build_yandex_route_url(
    origin_address,
    dest_address,
    *,
    mode = DEFAULT_ROUTE_MODE,
):
    """Build a Yandex.Maps route URL from the origin to the destination using the given travel mode."""
    if mode not in _VALID_MODES:
        mode = DEFAULT_ROUTE_MODE
    o = quote(origin_address.strip(), safe="")
    d = quote(dest_address.strip(), safe="")
    return f"https://yandex.ru/maps/?rtext={o}~{d}&rtt={mode}"

async def list_places(session, user):
    """List the user's saved places, default ones first, then alphabetically by name."""
    rows = await session.execute(
        select(Place)
        .where(Place.user_id == user.id)
        .order_by(Place.is_default.desc(), Place.name.asc())
    )
    return list(rows.scalars().all())

async def find_default_place(session, user):
    """Return the user's default place, or ``None`` if none is marked as default."""
    return (
        await session.execute(
            select(Place).where(
                and_(Place.user_id == user.id, Place.is_default.is_(True))
            )
        )
    ).scalar_one_or_none()

async def resolve_place_by_name(
    session, user, name
):
    """Resolve a free-form name to one of the user's places using exact, prefix, then substring match."""
    needle = name.strip().lower()
    if not needle:
        return None

    rows = (
        await session.execute(
            select(Place).where(Place.user_id == user.id)
        )
    ).scalars().all()

    if not rows:
        return None

    exact = [p for p in rows if p.name.lower() == needle]
    if exact:
        return exact[0]

    prefix = [p for p in rows if p.name.lower().startswith(needle)]
    if len(prefix) == 1:
        return prefix[0]

    contains = [p for p in rows if needle in p.name.lower()]
    if len(contains) == 1:
        return contains[0]
    return None

def _local_day_bounds(
    *, target_start, tz
):
    """Return (UTC start of local day containing ``target_start``, ``target_start``)."""
    local_target = target_start.astimezone(tz)
    local_day_start = local_target.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return local_day_start.astimezone(UTC), target_start

async def find_previous_event_location(
    session,
    user,
    *,
    target_start,
    tz,
    exclude_event_id=None,
    look_back = timedelta(hours=12),
):
    """Find the location of the user's most recent earlier event on the same local day, if any."""
    day_start, _ = _local_day_bounds(target_start=target_start, tz=tz)
    earliest = max(day_start, target_start - look_back)

    stmt = (
        select(Event)
        .where(
            and_(
                Event.user_id == user.id,
                Event.start_at < target_start,
                Event.start_at >= earliest,
                Event.all_day.is_(False),
                Event.location.is_not(None),
            )
        )
        .order_by(Event.start_at.desc())
        .limit(5)
    )
    rows = (await session.execute(stmt)).scalars().all()
    for ev in rows:
        if exclude_event_id is not None and ev.id == exclude_event_id:
            continue
        loc = (ev.location or "").strip()
        if loc:
            return loc
    return None

ROUTE_MARKER = "Маршрут: "

def append_route_to_description(
    description, route_url
):
    """Append or replace the route line in an event description, returning the updated text."""
    line = f"{ROUTE_MARKER}{route_url}"
    if description is None or not description.strip():
        return line
    out_lines = []
    replaced = False
    for raw in description.splitlines():
        if raw.startswith(ROUTE_MARKER):
            out_lines.append(line)
            replaced = True
        else:
            out_lines.append(raw)
    if not replaced:
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append(line)
    return "\n".join(out_lines)
