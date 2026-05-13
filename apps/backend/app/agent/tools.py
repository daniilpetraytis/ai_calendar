"""LangChain tools exposed to the LLM agent — list/create/move events, propose replan, query biometrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from langchain_core.tools import StructuredTool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.biometrics import service as bio_service
from app.calendar import service as cal_service
from app.categorize.service import record_correction
from app.db.models import Event, Place, Task, TaskStatus, User
from app.places import (
    append_route_to_description,
    build_yandex_route_url,
    find_default_place,
    find_previous_event_location,
)
from app.places import service as places_service
from app.scheduler import (
    PlanItem,
    SchedulerInput,
    SchedulerProposal,
)
from app.scheduler import (
    propose_replan as run_scheduler,
)
from app.scheduler.greedy import FixedBlock, ScheduledChange
from app.scheduler.service import (
    auto_schedule_user,
    find_slot_for_single,
    result_to_proposal,
)

@dataclass(slots=True)
class ProposalSlot:
    """Mutable holder for the latest scheduler proposal produced during a turn."""

    value: SchedulerProposal | None = None

@dataclass(slots=True)
class ToolContext:
    """Per-turn context shared by every tool: DB session, current user, and the proposal slot."""

    session: AsyncSession
    user: User
    proposal: ProposalSlot = field(default_factory=ProposalSlot)

def _user_tz(user):
    try:
        return ZoneInfo(user.timezone or "UTC")
    except Exception:
        return UTC

def _parse_dt(s, default_tz):
    dt = dateparser.isoparse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt

_VALID_CATEGORIES = frozenset([
    "work", "meeting", "sport", "health", "family",
    "hobby", "commute", "sleep", "leisure", "personal", "other",
])

def _event_to_dict(e, tz = None):
    start = e.start_at.astimezone(tz) if tz else e.start_at
    end = e.end_at.astimezone(tz) if tz else e.end_at
    return {
        "id": str(e.id),
        "title": e.title,
        "description": e.description,
        "location": e.location,
        "start_iso": start.isoformat(),
        "end_iso": end.isoformat(),
        "is_movable": e.is_movable,
        "priority": e.priority,
        "source": e.source.value,
        "category": e.category,
        "category_source": e.category_source,
    }

def _window_end_utc(
    *,
    now_utc,
    user_tz,
    horizon_days,
):
    local_now = now_utc.astimezone(user_tz)
    local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_window_end = local_day_start + timedelta(days=max(1, horizon_days))
    return local_window_end.astimezone(UTC)

async def _find_conflicts(
    session,
    user,
    *,
    start,
    end,
    exclude_id,
    tz,
):
    overlapping = await cal_service.list_events(session, user, start=start, end=end)
    out = []
    for e in overlapping:
        if exclude_id is not None and e.id == exclude_id:
            continue
        if e.all_day:
            continue
        out.append(_event_to_dict(e, tz))
    return out

async def _resolve_origin_address(
    session,
    user,
    *,
    target_start,
    tz,
    exclude_event_id = None,
):
    prev = await find_previous_event_location(
        session,
        user,
        target_start=target_start,
        tz=tz,
        exclude_event_id=exclude_event_id,
    )
    if prev:
        return prev
    default_place = await find_default_place(session, user)
    if default_place is not None:
        return default_place.address
    return None

def build_tools(ctx):
    """Build the list of ``StructuredTool`` instances bound to ``ctx`` for one agent turn.

    Each returned tool closes over the user's session, timezone, and proposal
    slot, so callers must build a fresh list per request."""
    user_tz = _user_tz(ctx.user)

    async def _attach_route(
        *,
        description,
        dest_address,
        target_start,
        exclude_event_id,
    ):
        """Append a Yandex Maps route URL to ``description`` when an origin can be resolved."""
        origin = await _resolve_origin_address(
            ctx.session,
            ctx.user,
            target_start=target_start,
            tz=user_tz,
            exclude_event_id=exclude_event_id,
        )
        if not origin:
            return description
        if origin.strip().lower() == dest_address.strip().lower():
            return description
        url = build_yandex_route_url(origin, dest_address)
        return append_route_to_description(description, url)

    async def list_events(start_iso, end_iso):
        """Return events whose interval overlaps the [start_iso, end_iso) window."""
        events = await cal_service.list_events(
            ctx.session,
            ctx.user,
            start=_parse_dt(start_iso, user_tz),
            end=_parse_dt(end_iso, user_tz),
        )
        return {"events": [_event_to_dict(e, user_tz) for e in events]}

    async def create_event(
        title,
        start_iso,
        end_iso,
        description = None,
        location = None,
        place_name = None,
    ):
        """Create a new event, resolving an optional saved-place name and
        attaching a Yandex Maps route link. De-duplicates against an identical
        event created in the last five minutes, and always returns the resulting
        event together with the list of overlapping events."""
        start_dt = _parse_dt(start_iso, user_tz)
        end_dt = _parse_dt(end_iso, user_tz)
        if end_dt <= start_dt:
            return {
                "error": (
                    f"end_iso ({end_iso}) must be AFTER start_iso ({start_iso}). "
                    "Re-compute: end = start + duration and try again."
                )
            }

        title_norm = title.strip()
        recent_threshold = datetime.now(UTC) - timedelta(minutes=5)
        existing_in_window = await cal_service.list_events(
            ctx.session, ctx.user, start=start_dt, end=end_dt
        )
        existing = None
        for ev in existing_in_window:
            ev_created = getattr(ev, "created_at", None)
            if (
                (ev.title or "").strip() == title_norm
                and ev.start_at.astimezone(UTC) == start_dt.astimezone(UTC)
                and ev.end_at.astimezone(UTC) == end_dt.astimezone(UTC)
                and ev_created is not None
                and ev_created >= recent_threshold
            ):
                existing = ev
                break
        if existing is not None:
            conflicts = await _find_conflicts(
                ctx.session,
                ctx.user,
                start=start_dt,
                end=end_dt,
                exclude_id=existing.id,
                tz=user_tz,
            )
            return {
                "created_event": _event_to_dict(existing, user_tz),
                "conflicts": conflicts,
                "duplicate_of_existing": True,
            }

        resolved_place = None
        place_lookup_failed = False
        if place_name:
            resolved_place = await places_service.resolve_place_by_name(
                ctx.session, ctx.user, place_name
            )
            if resolved_place is not None:
                location = resolved_place.address
            else:
                place_lookup_failed = True

        if location:
            description = await _attach_route(
                description=description,
                dest_address=location,
                target_start=start_dt,
                exclude_event_id=None,
            )

        event = await cal_service.create_event(
            ctx.session,
            ctx.user,
            title=title_norm,
            start=start_dt,
            end=end_dt,
            description=description,
            location=location,
        )
        conflicts = await _find_conflicts(
            ctx.session,
            ctx.user,
            start=start_dt,
            end=end_dt,
            exclude_id=event.id,
            tz=user_tz,
        )
        result = {
            "created_event": _event_to_dict(event, user_tz),
            "conflicts": conflicts,
        }
        if place_lookup_failed:
            result["place_lookup_failed"] = place_name
        return result

    async def create_event_series(
        title,
        start_local_time,
        end_local_time,
        from_date,
        until_date,
        weekdays = None,
        description = None,
        location = None,
    ):
        """Bulk-create the same daily block across a date range, optionally filtered by weekday.

        Returns counters for created/skipped days along with per-day conflicts."""
        from datetime import date as date_cls

        try:
            s_h, s_m = (int(x) for x in start_local_time.split(":"))
            e_h, e_m = (int(x) for x in end_local_time.split(":"))
        except ValueError:
            return {
                "error": (
                    "start_local_time / end_local_time must be 'HH:MM' "
                    f"(got {start_local_time!r} / {end_local_time!r})."
                )
            }
        if (e_h, e_m) <= (s_h, s_m):
            return {
                "error": (
                    f"end_local_time ({end_local_time}) must be AFTER "
                    f"start_local_time ({start_local_time})."
                )
            }

        try:
            d_from = date_cls.fromisoformat(from_date)
            d_until = date_cls.fromisoformat(until_date)
        except ValueError:
            return {
                "error": (
                    "from_date / until_date must be 'YYYY-MM-DD' "
                    f"(got {from_date!r} / {until_date!r})."
                )
            }
        if d_until < d_from:
            return {
                "error": (
                    f"until_date ({until_date}) is before from_date ({from_date})."
                )
            }

        weekday_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        weekday_filter = None
        if weekdays:
            wd_lower = {w.strip().lower()[:3] for w in weekdays}
            invalid = wd_lower - set(weekday_keys)
            if invalid:
                return {
                    "error": (
                        f"Unknown weekday(s): {sorted(invalid)}. "
                        f"Valid: {weekday_keys}."
                    )
                }
            weekday_filter = {weekday_keys.index(w) for w in wd_lower}

        created = []
        skipped = []
        conflicts_per_day = []
        cursor = d_from
        from datetime import timedelta as _td
        while cursor <= d_until:
            if weekday_filter is None or cursor.weekday() in weekday_filter:
                start_dt = datetime(
                    cursor.year, cursor.month, cursor.day, s_h, s_m, tzinfo=user_tz
                )
                end_dt = datetime(
                    cursor.year, cursor.month, cursor.day, e_h, e_m, tzinfo=user_tz
                )
                try:
                    event = await cal_service.create_event(
                        ctx.session,
                        ctx.user,
                        title=title,
                        start=start_dt,
                        end=end_dt,
                        description=description,
                        location=location,
                    )
                    day_conflicts = await _find_conflicts(
                        ctx.session,
                        ctx.user,
                        start=start_dt,
                        end=end_dt,
                        exclude_id=event.id,
                        tz=user_tz,
                    )
                    created.append(_event_to_dict(event, user_tz))
                    if day_conflicts:
                        conflicts_per_day.append(
                            {
                                "date": cursor.isoformat(),
                                "conflicts": day_conflicts,
                            }
                        )
                except Exception as exc:
                    skipped.append({"date": cursor.isoformat(), "reason": str(exc)})
            cursor = cursor + _td(days=1)

        return {
            "created_count": len(created),
            "created": created,
            "skipped": skipped,
            "conflicts_per_day": conflicts_per_day,
        }

    async def move_event(event_id, new_start_iso, new_end_iso):
        """Reschedule a single event to absolute ISO times and return any resulting conflicts."""
        new_start = _parse_dt(new_start_iso, user_tz)
        new_end = _parse_dt(new_end_iso, user_tz)
        if new_end <= new_start:
            return {
                "error": (
                    f"new_end_iso ({new_end_iso}) must be AFTER new_start_iso ({new_start_iso}). "
                    "Re-compute the times and try again."
                )
            }
        event = await cal_service.move_event(
            ctx.session,
            ctx.user,
            event_id=UUID(event_id),
            new_start=new_start,
            new_end=new_end,
        )
        conflicts = await _find_conflicts(
            ctx.session,
            ctx.user,
            start=new_start,
            end=new_end,
            exclude_id=event.id,
            tz=user_tz,
        )
        return {
            "updated_event": _event_to_dict(event, user_tz),
            "conflicts": conflicts,
        }

    async def shift_event(event_id, delta_minutes):
        """Shift a single event's start and end by ``delta_minutes``, preserving its duration."""
        if delta_minutes == 0:
            return {"error": "delta_minutes must be non-zero"}
        eid = UUID(event_id)
        event = await ctx.session.get(Event, eid)
        if event is None or event.user_id != ctx.user.id:
            return {"error": f"Event {event_id} not found"}
        delta = timedelta(minutes=delta_minutes)
        new_start = event.start_at + delta
        new_end = event.end_at + delta
        updated = await cal_service.move_event(
            ctx.session,
            ctx.user,
            event_id=eid,
            new_start=new_start,
            new_end=new_end,
        )
        conflicts = await _find_conflicts(
            ctx.session,
            ctx.user,
            start=new_start,
            end=new_end,
            exclude_id=updated.id,
            tz=user_tz,
        )
        return {
            "updated_event": _event_to_dict(updated, user_tz),
            "delta_minutes": delta_minutes,
            "conflicts": conflicts,
        }

    async def resize_event(event_id, end_delta_minutes):
        """Extend or shorten an event by moving only its end by ``end_delta_minutes`` (positive = extend)."""
        if end_delta_minutes == 0:
            return {"error": "end_delta_minutes must be non-zero"}
        eid = UUID(event_id)
        event = await ctx.session.get(Event, eid)
        if event is None or event.user_id != ctx.user.id:
            return {"error": f"Event {event_id} not found"}
        new_end = event.end_at + timedelta(minutes=end_delta_minutes)
        if new_end <= event.start_at:
            return {
                "error": (
                    f"end_delta_minutes={end_delta_minutes} would make the event end "
                    f"({new_end.isoformat()}) at or before its start "
                    f"({event.start_at.isoformat()}). Refuse."
                )
            }
        updated = await cal_service.move_event(
            ctx.session,
            ctx.user,
            event_id=eid,
            new_start=event.start_at,
            new_end=new_end,
        )
        conflicts = await _find_conflicts(
            ctx.session,
            ctx.user,
            start=updated.start_at,
            end=new_end,
            exclude_id=updated.id,
            tz=user_tz,
        )
        return {
            "updated_event": _event_to_dict(updated, user_tz),
            "end_delta_minutes": end_delta_minutes,
            "conflicts": conflicts,
        }

    async def update_event(
        event_id,
        title = None,
        description = None,
        location = None,
    ):
        """Patch an event's metadata (title / description / location) without changing its time."""
        event = await cal_service.update_event(
            ctx.session,
            ctx.user,
            event_id=UUID(event_id),
            title=title,
            description=description,
            location=location,
        )
        return {"updated_event": _event_to_dict(event, user_tz)}

    async def delete_event(event_id):
        """Delete the given event from the database (and the remote calendar if linked)."""
        await cal_service.delete_event(ctx.session, ctx.user, event_id=UUID(event_id))
        return {"deleted_event_id": event_id}

    async def propose_replan(
        reason,
        horizon_days = 1,
        day_start_hhmm = "09:00",
        day_end_hhmm = "20:00",
    ):
        """Produce a multi-change rearrangement proposal over the next ``horizon_days``
        and stash it on ``ctx.proposal`` for the approval UI."""
        from datetime import time

        now = datetime.now(UTC)
        end = now + timedelta(days=horizon_days)
        events = await cal_service.list_events(ctx.session, ctx.user, start=now, end=end)

        fixed = []
        items = []
        for e in events:
            if not e.is_movable:
                fixed.append(FixedBlock(start=e.start_at, end=e.end_at, title=e.title))
            else:
                items.append(
                    PlanItem(
                        kind="event",
                        id=e.id,
                        title=e.title,
                        duration_minutes=int((e.end_at - e.start_at).total_seconds() // 60),
                        priority=e.priority,
                        current_start=e.start_at,
                        current_end=e.end_at,
                    )
                )

        tasks = (
            await ctx.session.execute(
                select(Task).where(Task.user_id == ctx.user.id, Task.status == "pending")
            )
        ).scalars().all()
        for t in tasks:
            items.append(
                PlanItem(
                    kind="task",
                    id=t.id,
                    title=t.title,
                    duration_minutes=t.duration_minutes,
                    priority=t.priority,
                    earliest_at=t.earliest_at,
                    deadline_at=t.deadline_at,
                )
            )

        def _hhmm(s):
            h, m = s.split(":")
            return time(int(h), int(m))

        proposal = run_scheduler(
            SchedulerInput(
                now=now,
                day_start=_hhmm(day_start_hhmm),
                day_end=_hhmm(day_end_hhmm),
                horizon_days=max(1, horizon_days),
                fixed=fixed,
                items=items,
            )
        )
        ctx.proposal.value = proposal

        return {
            "reason": reason,
            "summary": proposal.summary,
            "changes": [
                {
                    "op": c.op,
                    "title": c.item.title,
                    "kind": c.item.kind,
                    "id": str(c.item.id),
                    "new_start_iso": c.new_start.astimezone(user_tz).isoformat() if c.new_start else None,
                    "new_end_iso": c.new_end.astimezone(user_tz).isoformat() if c.new_end else None,
                    "reason": c.reason,
                }
                for c in proposal.changes
            ],
            "unscheduled": [
                {"title": u.title, "kind": u.kind, "id": str(u.id)}
                for u in proposal.unscheduled
            ],
            "needs_user_approval": True,
        }

    async def propose_shift(
        delta_minutes,
        horizon_days = 1,
        include_immovable = False,
    ):
        """Propose a literal shift of every future movable event by ``delta_minutes`` for user approval.

        Already-started events and (by default) immovable events are skipped and reported separately."""
        if delta_minutes == 0:
            return {"error": "delta_minutes must be non-zero"}

        now = datetime.now(UTC)
        end = _window_end_utc(now_utc=now, user_tz=user_tz, horizon_days=horizon_days)
        events = await cal_service.list_events(ctx.session, ctx.user, start=now, end=end)

        delta = timedelta(minutes=delta_minutes)
        changes = []
        skipped_immovable = []
        skipped_already_started = []

        for e in events:
            if e.all_day:
                continue
            if e.start_at < now:
                skipped_already_started.append(_event_to_dict(e, user_tz))
                continue
            if not e.is_movable and not include_immovable:
                skipped_immovable.append(_event_to_dict(e, user_tz))
                continue

            duration_minutes = max(1, int((e.end_at - e.start_at).total_seconds() // 60))
            item = PlanItem(
                kind="event",
                id=e.id,
                title=e.title,
                duration_minutes=duration_minutes,
                priority=e.priority,
                current_start=e.start_at,
                current_end=e.end_at,
            )
            changes.append(
                ScheduledChange(
                    op="move",
                    item=item,
                    new_start=e.start_at + delta,
                    new_end=e.end_at + delta,
                    reason=f"shifted by {delta_minutes:+d} min",
                )
            )

        sign = "later" if delta_minutes > 0 else "earlier"
        summary = (
            f"Shift {len(changes)} event(s) by {abs(delta_minutes)} min {sign}."
            if changes
            else f"No future events in the next {max(1, horizon_days)} day(s) to shift."
        )
        proposal = SchedulerProposal(summary=summary, changes=changes, unscheduled=[])
        ctx.proposal.value = proposal

        return {
            "summary": summary,
            "delta_minutes": delta_minutes,
            "horizon_days": horizon_days,
            "changes": [
                {
                    "op": c.op,
                    "title": c.item.title,
                    "id": str(c.item.id),
                    "current_start_iso": (
                        c.item.current_start.astimezone(user_tz).isoformat()
                        if c.item.current_start
                        else None
                    ),
                    "current_end_iso": (
                        c.item.current_end.astimezone(user_tz).isoformat()
                        if c.item.current_end
                        else None
                    ),
                    "new_start_iso": c.new_start.astimezone(user_tz).isoformat() if c.new_start else None,
                    "new_end_iso": c.new_end.astimezone(user_tz).isoformat() if c.new_end else None,
                }
                for c in changes
            ],
            "skipped_immovable": skipped_immovable,
            "skipped_already_started": skipped_already_started,
            "needs_user_approval": bool(changes),
        }

    async def finish_event_now_and_propose_shift_today(
        event_id,
        include_immovable = False,
    ):
        """Extend ``event_id`` so it ends right now and propose shifting the
        remaining events of today later by the same delay."""
        eid = UUID(event_id)
        event = await ctx.session.get(Event, eid)
        if event is None or event.user_id != ctx.user.id:
            return {"error": f"Event {event_id} not found"}
        if event.all_day:
            return {"error": "Cannot extend all-day events to current time."}
        original_end = event.end_at

        now = datetime.now(UTC)
        if now < event.start_at:
            return {
                "error": (
                    f"Event starts in the future ({event.start_at.isoformat()}); "
                    "cannot finish it now."
                )
            }

        delay_seconds = (now - original_end).total_seconds()
        delay_minutes = max(0, int((delay_seconds + 59) // 60))
        if delay_minutes == 0:
            return {
                "summary": (
                    f"Event '{event.title}' has no delay relative to current time; "
                    "nothing to shift."
                ),
                "updated_event": _event_to_dict(event, user_tz),
                "delay_minutes": 0,
                "changes": [],
                "skipped_immovable": [],
                "skipped_already_started": [],
                "needs_user_approval": False,
            }

        updated = await cal_service.move_event(
            ctx.session,
            ctx.user,
            event_id=eid,
            new_start=event.start_at,
            new_end=now,
        )
        extension_conflicts = await _find_conflicts(
            ctx.session,
            ctx.user,
            start=updated.start_at,
            end=updated.end_at,
            exclude_id=updated.id,
            tz=user_tz,
        )

        end = _window_end_utc(now_utc=now, user_tz=user_tz, horizon_days=1)
        events = await cal_service.list_events(
            ctx.session,
            ctx.user,
            start=original_end,
            end=end,
        )

        delta = timedelta(minutes=delay_minutes)
        changes = []
        skipped_immovable = []
        skipped_already_started = []

        for e in events:
            if e.id == eid or e.all_day:
                continue
            if e.start_at < original_end:
                skipped_already_started.append(_event_to_dict(e, user_tz))
                continue
            if not e.is_movable and not include_immovable:
                skipped_immovable.append(_event_to_dict(e, user_tz))
                continue

            duration_minutes = max(1, int((e.end_at - e.start_at).total_seconds() // 60))
            item = PlanItem(
                kind="event",
                id=e.id,
                title=e.title,
                duration_minutes=duration_minutes,
                priority=e.priority,
                current_start=e.start_at,
                current_end=e.end_at,
            )
            changes.append(
                ScheduledChange(
                    op="move",
                    item=item,
                    new_start=e.start_at + delta,
                    new_end=e.end_at + delta,
                    reason=(
                        f"shifted by +{delay_minutes} min because "
                        f"'{updated.title}' was extended to now"
                    ),
                )
            )

        summary = (
            f"Extended '{updated.title}' to now and shifted {len(changes)} "
            f"event(s) later by {delay_minutes} min for the rest of today."
        )
        proposal = SchedulerProposal(summary=summary, changes=changes, unscheduled=[])
        ctx.proposal.value = proposal

        return {
            "summary": summary,
            "updated_event": _event_to_dict(updated, user_tz),
            "delay_minutes": delay_minutes,
            "extension_conflicts": extension_conflicts,
            "changes": [
                {
                    "op": c.op,
                    "title": c.item.title,
                    "id": str(c.item.id),
                    "current_start_iso": (
                        c.item.current_start.astimezone(user_tz).isoformat()
                        if c.item.current_start
                        else None
                    ),
                    "current_end_iso": (
                        c.item.current_end.astimezone(user_tz).isoformat()
                        if c.item.current_end
                        else None
                    ),
                    "new_start_iso": c.new_start.astimezone(user_tz).isoformat() if c.new_start else None,
                    "new_end_iso": c.new_end.astimezone(user_tz).isoformat() if c.new_end else None,
                }
                for c in changes
            ],
            "skipped_immovable": skipped_immovable,
            "skipped_already_started": skipped_already_started,
            "needs_user_approval": bool(changes),
        }

    async def set_event_category(event_id, category):
        """Override an event's category and record the correction for the categoriser."""
        if category not in _VALID_CATEGORIES:
            return {
                "error": f"Unknown category '{category}'. "
                f"Valid: {', '.join(sorted(_VALID_CATEGORIES))}"
            }
        event = await ctx.session.get(Event, UUID(event_id))
        if event is None or event.user_id != ctx.user.id:
            return {"error": f"Event {event_id} not found"}
        await record_correction(ctx.session, ctx.user, event, category)
        return {
            "event_id": event_id,
            "title": event.title,
            "category": event.category,
            "category_source": event.category_source,
            "start_iso": event.start_at.astimezone(user_tz).isoformat(),
        }

    async def get_stats(period = "week"):
        """Aggregate hours spent per category over ``period`` (``day`` / ``week`` / ``month``)."""
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from app.calendar.service import list_events as list_evs

        valid_periods = {"day", "week", "month"}
        if period not in valid_periods:
            period = "week"

        try:
            tz = ZoneInfo(ctx.user.timezone or "UTC")
        except (ZoneInfoNotFoundError, KeyError):
            tz = ZoneInfo("UTC")

        now = datetime.now(UTC)
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif period == "week":
            days_since_monday = now.astimezone(tz).weekday()
            monday = now.astimezone(tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=days_since_monday)
            start = monday.astimezone(UTC)
            end = start + timedelta(weeks=1)
        else:  # month
            local_now = now.astimezone(tz)
            start = local_now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ).astimezone(UTC)
            if local_now.month == 12:
                end = start.replace(year=local_now.year + 1, month=1)
            else:
                end = start.replace(month=local_now.month + 1)

        events = await list_evs(ctx.session, ctx.user, start=start, end=end)
        totals = {}
        for e in events:
            cat = e.category or "unclassified"
            mins = max(0, int((e.end_at - e.start_at).total_seconds() / 60))
            totals[cat] = totals.get(cat, 0) + mins

        rows = sorted(totals.items(), key=lambda x: -x[1])
        lines = [f"{cat}: {m // 60}h {m % 60}m" for cat, m in rows]
        total_mins = sum(totals.values())
        return {
            "period": period,
            "total": f"{total_mins // 60}h {total_mins % 60}m",
            "by_category": lines,
        }

    async def create_task(
        title,
        duration_minutes = 30,
        deadline_iso = None,
        earliest_iso = None,
        priority = 5,
        focus_required = "shallow",
        description = None,
        splittable = False,
        auto_schedule = True,
    ):
        """Persist a new task and, when ``auto_schedule`` is true, immediately place it in the next free slot."""
        focus = focus_required if focus_required in ("deep", "shallow", "admin") else "shallow"
        deadline_dt = _parse_dt(deadline_iso, user_tz) if deadline_iso else None
        earliest_dt = _parse_dt(earliest_iso, user_tz) if earliest_iso else None

        task = Task(
            tenant_id=ctx.user.tenant_id,
            user_id=ctx.user.id,
            title=title,
            description=description,
            duration_minutes=max(5, duration_minutes),
            priority=max(0, min(10, priority)),
            deadline_at=deadline_dt,
            earliest_at=earliest_dt,
            focus_required=focus,
            splittable=splittable,
            estimated_minutes=max(5, duration_minutes),
        )
        ctx.session.add(task)
        await ctx.session.flush()

        scheduled_start = None
        scheduled_end = None
        if auto_schedule:
            slot = await find_slot_for_single(
                ctx.session,
                ctx.user,
                duration_minutes=task.duration_minutes,
                deadline_at=task.deadline_at,
                earliest_at=task.earliest_at,
                focus_required=task.focus_required,
            )
            if slot is not None:
                scheduled_start, scheduled_end = slot
                event = await cal_service.create_event(
                    ctx.session,
                    ctx.user,
                    title=task.title,
                    start=scheduled_start,
                    end=scheduled_end,
                    description=task.description,
                )
                task.scheduled_event_id = event.id
                task.status = TaskStatus.SCHEDULED
                task.auto_scheduled = True
        return {
            "task_id": str(task.id),
            "title": task.title,
            "duration_minutes": task.duration_minutes,
            "focus_required": task.focus_required,
            "deadline_iso": (
                task.deadline_at.astimezone(user_tz).isoformat()
                if task.deadline_at
                else None
            ),
            "scheduled_start_iso": (
                scheduled_start.astimezone(user_tz).isoformat()
                if scheduled_start
                else None
            ),
            "scheduled_end_iso": (
                scheduled_end.astimezone(user_tz).isoformat()
                if scheduled_end
                else None
            ),
            "status": task.status.value if hasattr(task.status, "value") else task.status,
        }

    async def list_tasks(status = None):
        """Return the user's tasks, optionally filtered by status."""
        stmt = select(Task).where(Task.user_id == ctx.user.id)
        if status:
            try:
                stmt = stmt.where(Task.status == TaskStatus(status))
            except ValueError:
                return {
                    "error": (
                        f"Unknown status '{status}'. "
                        "Valid: pending, scheduled, done, skipped."
                    )
                }
        rows = (
            await ctx.session.execute(stmt.order_by(Task.created_at.desc()))
        ).scalars().all()
        return {
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "duration_minutes": t.duration_minutes,
                    "priority": t.priority,
                    "focus_required": t.focus_required,
                    "deadline_iso": (
                        t.deadline_at.astimezone(user_tz).isoformat()
                        if t.deadline_at
                        else None
                    ),
                    "status": t.status.value if hasattr(t.status, "value") else t.status,
                    "scheduled_event_id": (
                        str(t.scheduled_event_id) if t.scheduled_event_id else None
                    ),
                }
                for t in rows
            ]
        }

    async def schedule_pending_tasks(
        horizon_days = 7, apply_immediately = False
    ):
        """Bulk-schedule pending tasks over the next ``horizon_days``.

        With ``apply_immediately=True`` the plan is committed; otherwise a
        proposal is stashed on ``ctx.proposal`` for user approval."""
        result, run = await auto_schedule_user(
            ctx.session,
            ctx.user,
            horizon_days=max(1, horizon_days),
            apply=apply_immediately,
            trigger="agent_chat",
        )
        if apply_immediately:
            return {
                "applied": True,
                "run_id": str(run.id),
                "scheduled_count": len(result.scheduled),
                "unscheduled_count": len(result.unscheduled),
                "scheduled": [
                    {
                        "task_id": str(c.task_id),
                        "title": c.title,
                        "start_iso": c.start.astimezone(user_tz).isoformat(),
                        "end_iso": c.end.astimezone(user_tz).isoformat(),
                    }
                    for c in result.scheduled
                ],
            }

        scheduler_changes = []
        for c in result.scheduled:
            scheduler_changes.append(
                ScheduledChange(
                    op="create",
                    item=PlanItem(
                        kind="task",
                        id=c.task_id,
                        title=(
                            c.title
                            if c.chunk_total <= 1
                            else f"{c.title} ({c.chunk_index + 1}/{c.chunk_total})"
                        ),
                        duration_minutes=int((c.end - c.start).total_seconds() // 60),
                    ),
                    new_start=c.start,
                    new_end=c.end,
                    reason=c.reason,
                )
            )
        unscheduled_items = [
            PlanItem(
                kind="task",
                id=tid,
                title=title,
                duration_minutes=0,
            )
            for (tid, title, _reason) in result.unscheduled
        ]
        proposal_summary = result_to_proposal(result, summary_prefix="Auto-schedule")[
            "summary"
        ]
        ctx.proposal.value = SchedulerProposal(
            summary=proposal_summary,
            changes=scheduler_changes,
            unscheduled=unscheduled_items,
        )
        return {
            "needs_user_approval": True,
            "run_id": str(run.id),
            "summary": proposal_summary,
            "scheduled_count": len(result.scheduled),
            "unscheduled": [
                {"task_id": str(tid), "title": title, "reason": reason}
                for (tid, title, reason) in result.unscheduled
            ],
        }

    async def find_focus_block(
        duration_minutes,
        before_iso = None,
        kind = "deep",
    ):
        """Suggest a single free slot suitable for focused work, without creating anything."""
        focus = kind if kind in ("deep", "shallow", "admin") else "deep"
        deadline = _parse_dt(before_iso, user_tz) if before_iso else None
        slot = await find_slot_for_single(
            ctx.session,
            ctx.user,
            duration_minutes=max(5, duration_minutes),
            deadline_at=deadline,
            focus_required=focus,
        )
        if slot is None:
            return {"start_iso": None, "end_iso": None}
        return {
            "start_iso": slot[0].astimezone(user_tz).isoformat(),
            "end_iso": slot[1].astimezone(user_tz).isoformat(),
        }

    async def complete_task(
        task_id, actual_duration_minutes = None
    ):
        """Mark a task done and record the actual minutes spent for estimate-vs-actual learning."""
        task = await ctx.session.get(Task, UUID(task_id))
        if task is None or task.user_id != ctx.user.id:
            return {"error": f"Task {task_id} not found"}
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        if actual_duration_minutes is not None:
            if task.estimated_minutes is None:
                task.estimated_minutes = task.duration_minutes
            task.duration_minutes = max(1, actual_duration_minutes)
        return {
            "task_id": task_id,
            "title": task.title,
            "completed_at_iso": task.completed_at.astimezone(user_tz).isoformat(),
        }

    async def defer_task(
        task_id, to_iso = None, reason = ""
    ):
        """Push a task back to pending, clearing any existing calendar slot so the
        scheduler picks a fresh one."""
        task = await ctx.session.get(Task, UUID(task_id))
        if task is None or task.user_id != ctx.user.id:
            return {"error": f"Task {task_id} not found"}
        if task.scheduled_event_id is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await cal_service.delete_event(
                    ctx.session, ctx.user, event_id=task.scheduled_event_id
                )
            task.scheduled_event_id = None
        task.status = TaskStatus.PENDING
        task.auto_scheduled = False
        if to_iso:
            task.earliest_at = _parse_dt(to_iso, user_tz)
        return {
            "task_id": task_id,
            "title": task.title,
            "status": task.status.value,
            "earliest_at_iso": (
                task.earliest_at.astimezone(user_tz).isoformat()
                if task.earliest_at
                else None
            ),
            "reason": reason,
        }

    async def list_places():
        """List the user's saved places (name, address, default flag)."""
        rows = await places_service.list_places(ctx.session, ctx.user)
        return {
            "places": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "address": p.address,
                    "is_default": p.is_default,
                }
                for p in rows
            ]
        }

    async def add_place(
        name,
        address,
        is_default = False,
    ):
        """Add a saved place; when ``is_default`` is true, any previous default is cleared."""
        name_clean = name.strip()
        address_clean = address.strip()
        if not name_clean or not address_clean:
            return {"error": "Both name and address are required."}
        existing = (
            await ctx.session.execute(
                select(Place).where(
                    Place.user_id == ctx.user.id, Place.name == name_clean
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "error": f"Place '{name_clean}' already exists. "
                "Use update_place or pick a different name."
            }
        if is_default:
            from sqlalchemy import update as sa_update

            await ctx.session.execute(
                sa_update(Place)
                .where(Place.user_id == ctx.user.id, Place.is_default.is_(True))
                .values(is_default=False)
            )
        place = Place(
            tenant_id=ctx.user.tenant_id,
            user_id=ctx.user.id,
            name=name_clean,
            address=address_clean,
            is_default=is_default,
        )
        ctx.session.add(place)
        await ctx.session.flush()
        return {
            "place": {
                "id": str(place.id),
                "name": place.name,
                "address": place.address,
                "is_default": place.is_default,
            }
        }

    async def delete_place(name):
        """Delete a saved place by (fuzzy) name."""
        place = await places_service.resolve_place_by_name(
            ctx.session, ctx.user, name
        )
        if place is None:
            return {"error": f"Place '{name}' not found."}
        await ctx.session.delete(place)
        return {"deleted": {"id": str(place.id), "name": place.name}}

    async def set_default_place(name):
        """Mark the named place as the user's default origin for route building."""
        place = await places_service.resolve_place_by_name(
            ctx.session, ctx.user, name
        )
        if place is None:
            return {"error": f"Place '{name}' not found."}
        from sqlalchemy import update as sa_update

        await ctx.session.execute(
            sa_update(Place)
            .where(
                Place.user_id == ctx.user.id,
                Place.is_default.is_(True),
                Place.id != place.id,
            )
            .values(is_default=False)
        )
        place.is_default = True
        await ctx.session.flush()
        return {
            "place": {
                "id": str(place.id),
                "name": place.name,
                "address": place.address,
                "is_default": True,
            }
        }

    async def create_commute_event(
        target_event_id,
        duration_minutes,
    ):
        """Create a «Дорога» event of ``duration_minutes`` ending right when the
        target event starts, with a Yandex Maps route URL in the description when both
        origin and destination resolve."""
        if duration_minutes <= 0:
            return {"error": "duration_minutes must be positive"}
        try:
            tid = UUID(target_event_id)
        except (ValueError, TypeError):
            return {"error": f"Invalid target_event_id: {target_event_id!r}"}
        target = await ctx.session.get(Event, tid)
        if target is None or target.user_id != ctx.user.id:
            return {"error": f"Target event {target_event_id} not found"}
        if target.all_day:
            return {"error": "Cannot attach a commute event to an all-day event."}

        commute_start = target.start_at - timedelta(minutes=duration_minutes)
        commute_end = target.start_at

        description = None
        dest = (target.location or "").strip() or None
        origin = await _resolve_origin_address(
            ctx.session,
            ctx.user,
            target_start=target.start_at,
            tz=user_tz,
            exclude_event_id=target.id,
        )
        if origin and dest and origin.strip().lower() != dest.strip().lower():
            description = build_yandex_route_url(origin, dest)

        event = await cal_service.create_event(
            ctx.session,
            ctx.user,
            title="Дорога",
            start=commute_start,
            end=commute_end,
            description=description,
            location=origin,
        )
        event.category = "commute"
        event.category_source = "agent"
        await ctx.session.flush()

        conflicts = await _find_conflicts(
            ctx.session,
            ctx.user,
            start=commute_start,
            end=commute_end,
            exclude_id=event.id,
            tz=user_tz,
        )
        return {
            "created_event": _event_to_dict(event, user_tz),
            "duration_minutes": duration_minutes,
            "origin": origin,
            "destination": dest,
            "route_url": description,
            "conflicts": conflicts,
        }

    async def get_biometric_context():
        """Return today's Whoop recovery/sleep/strain snapshot plus a 7-day trend, or a ``connected: false`` stub."""
        integration = await bio_service.get_whoop_integration(ctx.session, ctx.user)
        if integration is None:
            return {"connected": False, "available": False}
        snap = await bio_service.get_today_snapshot(ctx.session, ctx.user)
        history = await bio_service.get_history(ctx.session, ctx.user, days=14)
        return bio_service.summarize_for_agent(snap, history)

    async def get_event_workout_stats(event_id):
        """Return the Whoop workout snapshot attached to a past sport event, or ``{"available": False}``."""
        whoop = await bio_service.get_event_workout_extra(
            ctx.session, ctx.user, event_id
        )
        if whoop is None:
            return {"available": False}
        return {"available": True, **whoop}

    def tool(coroutine, name):
        """Wrap an async closure into a ``StructuredTool`` for LangChain."""
        return StructuredTool.from_function(
            coroutine=coroutine,
            name=name,
            description=name,
        )

    return [
        tool(list_events, "list_events"),
        tool(create_event, "create_event"),
        tool(create_event_series, "create_event_series"),
        tool(move_event, "move_event"),
        tool(shift_event, "shift_event"),
        tool(resize_event, "resize_event"),
        tool(update_event, "update_event"),
        tool(delete_event, "delete_event"),
        tool(propose_replan, "propose_replan"),
        tool(propose_shift, "propose_shift"),
        tool(
            finish_event_now_and_propose_shift_today,
            "finish_event_now_and_propose_shift_today",
        ),
        tool(set_event_category, "set_event_category"),
        tool(get_stats, "get_stats"),
        tool(create_task, "create_task"),
        tool(list_tasks, "list_tasks"),
        tool(schedule_pending_tasks, "schedule_pending_tasks"),
        tool(find_focus_block, "find_focus_block"),
        tool(complete_task, "complete_task"),
        tool(defer_task, "defer_task"),
        tool(list_places, "list_places"),
        tool(add_place, "add_place"),
        tool(delete_place, "delete_place"),
        tool(set_default_place, "set_default_place"),
        tool(create_commute_event, "create_commute_event"),
        tool(get_biometric_context, "get_biometric_context"),
        tool(get_event_workout_stats, "get_event_workout_stats"),
    ]
