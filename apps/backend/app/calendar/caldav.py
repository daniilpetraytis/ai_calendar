"""Integration wrapper around the CalDAV protocol (RFC 4791) — list/create/patch/delete events on a remote calendar, with Yandex defaults."""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_lib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import caldav
import icalendar
from caldav.lib.error import AuthorizationError, NotFoundError

YANDEX_CALDAV_URL = "https://caldav.yandex.ru"

log = logging.getLogger(__name__)

@dataclass(slots=True)
class CalDAVEvent:
    """Parsed VEVENT — the subset of iCalendar fields this app cares about."""

    uid: str
    summary: str
    description: str | None
    location: str | None
    start: datetime
    end: datetime
    all_day: bool
    etag: str | None
    raw_ical: str

def _ical_to_event(ical_str, etag):
    """Parse the first VEVENT in ``ical_str`` into a ``CalDAVEvent``; return ``None`` if absent."""
    cal = icalendar.Calendar.from_ical(ical_str)
    for component in cal.walk("VEVENT"):
        uid = str(component.get("UID", ""))
        summary = str(component.get("SUMMARY", "(no title)"))
        description = component.get("DESCRIPTION")
        location = component.get("LOCATION")
        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        if dtstart is None or dtend is None:
            continue

        start_val = dtstart.dt
        end_val = dtend.dt
        all_day = not isinstance(start_val, datetime)
        if all_day:
            start = datetime.combine(start_val, datetime.min.time(), tzinfo=timezone.utc)
            end = datetime.combine(end_val, datetime.min.time(), tzinfo=timezone.utc)
        else:
            start = _ensure_aware(start_val)
            end = _ensure_aware(end_val)

        return CalDAVEvent(
            uid=uid,
            summary=summary,
            description=str(description) if description else None,
            location=str(location) if location else None,
            start=start,
            end=end,
            all_day=all_day,
            etag=etag,
            raw_ical=ical_str,
        )
    return None

def _ensure_aware(dt):
    """Treat a naive datetime as UTC; otherwise return it unchanged."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _build_vevent(
    *,
    uid,
    title,
    start,
    end,
    description,
    location,
):
    """Serialise a single VEVENT into a fully formed iCalendar payload."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//ai-calendar//EN")
    cal.add("version", "2.0")
    ev = icalendar.Event()
    ev.add("uid", uid)
    ev.add("summary", title)
    ev.add("dtstart", start.astimezone(timezone.utc))
    ev.add("dtend", end.astimezone(timezone.utc))
    ev.add("dtstamp", datetime.now(timezone.utc))
    if description:
        ev.add("description", description)
    if location:
        ev.add("location", location)
    cal.add_component(ev)
    return cal.to_ical().decode()

@dataclass(slots=True)
class CalDAVAuth:
    """Connection credentials for a CalDAV server (URL + basic auth)."""

    url: str
    username: str
    password: str

class CalDAVClient:
    """Async wrapper around the synchronous ``caldav`` library, with a single bound calendar per instance."""

    def __init__(self, auth, calendar_url = None):
        self._auth = auth
        self._calendar_url = calendar_url
        self._client = None
        self._calendar = None

    def _ensure_open(self):
        """Lazily open the DAV client and resolve the target calendar URL on first use."""
        if self._client is not None and self._calendar is not None:
            return
        self._client = caldav.DAVClient(
            url=self._auth.url, username=self._auth.username, password=self._auth.password
        )
        if self._calendar_url:
            self._calendar = caldav.Calendar(client=self._client, url=self._calendar_url)
            return
        principal = self._client.principal()
        calendars = principal.calendars()
        if not calendars:
            raise RuntimeError("No CalDAV calendars found for this account")
        self._calendar = self._pick_default(calendars)
        self._calendar_url = str(self._calendar.url)

    @staticmethod
    def _pick_default(calendars):
        """Pick the user's primary calendar (Yandex's ``events-default``), or fall back to the first one."""
        for cal in calendars:
            url = str(cal.url)
            if "events-default" in url:
                return cal
        return calendars[0]

    async def discover(self):
        """Resolve and cache the calendar URL on the bound principal, returning it."""

        def _do():
            self._ensure_open()
            assert self._calendar_url is not None
            return self._calendar_url

        return await asyncio.to_thread(_do)

    async def get_ctag(self):
        """Return the collection's CTag for cheap change detection, or ``None`` when unavailable."""
        def _do():
            self._ensure_open()
            assert self._calendar is not None
            try:
                ctag = self._calendar.get_property(caldav.elements.dav.GetCTag())
                return str(ctag) if ctag else None
            except Exception:
                return None

        return await asyncio.to_thread(_do)

    async def list_events(
        self,
        *,
        time_min = None,
        time_max = None,
    ):
        """Return parsed ``CalDAVEvent`` objects in the optional time window, expanding recurrences when both bounds are given."""
        expand = time_min is not None and time_max is not None

        def _do():
            self._ensure_open()
            assert self._calendar is not None
            try:
                items = self._calendar.search(
                    start=time_min,
                    end=time_max,
                    event=True,
                    expand=expand,
                )
            except NotFoundError:
                items = []
            out = []
            for item in items:
                try:
                    raw = item.data if isinstance(item.data, str) else item.data.decode()
                    etag = getattr(item, "etag", None)
                    parsed = _ical_to_event(raw, etag)
                    if parsed is not None:
                        out.append(parsed)
                except Exception as exc:  # one bad event shouldn't kill the whole sync
                    log.warning("caldav_parse_failed", extra={"error": str(exc)})
            return out

        return await asyncio.to_thread(_do)

    async def create_event(
        self,
        *,
        title,
        start,
        end,
        description = None,
        location = None,
    ):
        """Create a new VEVENT on the bound calendar and return the parsed result."""
        def _do():
            self._ensure_open()
            assert self._calendar is not None
            uid = f"{uuid_lib.uuid4()}@ai-calendar"
            ical = _build_vevent(
                uid=uid,
                title=title,
                start=start,
                end=end,
                description=description,
                location=location,
            )
            saved = self._calendar.save_event(ical)
            etag = getattr(saved, "etag", None)
            raw = saved.data if isinstance(saved.data, str) else saved.data.decode()
            event = _ical_to_event(raw, etag)
            assert event is not None
            return event

        return await asyncio.to_thread(_do)

    async def patch_event(
        self,
        event_uid,
        *,
        title = None,
        start = None,
        end = None,
        description = None,
        location = None,
    ):
        """Patch the named VEVENT in place, replacing only the supplied fields and bumping LAST-MODIFIED."""
        def _do():
            self._ensure_open()
            assert self._calendar is not None
            obj = self._calendar.event_by_uid(event_uid)
            cal = icalendar.Calendar.from_ical(
                obj.data if isinstance(obj.data, str) else obj.data.decode()
            )
            for ev in cal.walk("VEVENT"):
                if title is not None:
                    ev["SUMMARY"] = title
                if description is not None:
                    if "DESCRIPTION" in ev:
                        del ev["DESCRIPTION"]
                    ev.add("DESCRIPTION", description)
                if location is not None:
                    if "LOCATION" in ev:
                        del ev["LOCATION"]
                    ev.add("LOCATION", location)
                if start is not None:
                    if "DTSTART" in ev:
                        del ev["DTSTART"]
                    ev.add("DTSTART", start.astimezone(timezone.utc))
                if end is not None:
                    if "DTEND" in ev:
                        del ev["DTEND"]
                    ev.add("DTEND", end.astimezone(timezone.utc))
                if "LAST-MODIFIED" in ev:
                    del ev["LAST-MODIFIED"]
                ev.add("LAST-MODIFIED", datetime.now(timezone.utc))
                break
            obj.data = cal.to_ical().decode()
            obj.save()
            etag = getattr(obj, "etag", None)
            raw = obj.data if isinstance(obj.data, str) else obj.data.decode()
            event = _ical_to_event(raw, etag)
            assert event is not None
            return event

        return await asyncio.to_thread(_do)

    async def delete_event(self, event_uid):
        """Delete the named VEVENT on the bound calendar; missing events are ignored."""
        def _do():
            self._ensure_open()
            assert self._calendar is not None
            try:
                obj = self._calendar.event_by_uid(event_uid)
                obj.delete()
            except NotFoundError:
                return

        await asyncio.to_thread(_do)

def yandex_auth(email, app_password):
    """Build a ``CalDAVAuth`` for the public Yandex CalDAV endpoint."""
    return CalDAVAuth(url=YANDEX_CALDAV_URL, username=email, password=app_password)

__all__ = [
    "CalDAVAuth",
    "CalDAVClient",
    "CalDAVEvent",
    "AuthorizationError",
    "NotFoundError",
    "yandex_auth",
    "YANDEX_CALDAV_URL",
]
