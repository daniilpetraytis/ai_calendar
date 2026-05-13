"""Events REST API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import EventCreate, EventOut, EventUpdate
from app.calendar import service
from app.calendar.service import IntegrationNotConnected
from app.categorize.service import record_correction
from app.deps import CurrentUser, DbSession

router = APIRouter()


@router.get("", response_model=list[EventOut])
async def list_events(
    user: CurrentUser,
    session: DbSession,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
):
    now = datetime.now(timezone.utc)
    # Default window is wide enough to surface historical Whoop-linked
    # workouts (auto-created on initial Whoop connect for the past month)
    # while still bounded enough to be cheap.
    start = start or (now - timedelta(days=60))
    end = end or (now + timedelta(days=30))
    rows = await service.list_events(session, user, start=start, end=end)
    return rows


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreate, user: CurrentUser, session: DbSession
) -> EventOut:
    if body.end_at <= body.start_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_at must be after start_at")
    event = await service.create_event(
        session,
        user,
        title=body.title,
        start=body.start_at,
        end=body.end_at,
        description=body.description,
        location=body.location,
        is_movable=body.is_movable,
        priority=body.priority,
    )
    return event  # type: ignore[return-value]


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: UUID, body: EventUpdate, user: CurrentUser, session: DbSession
) -> EventOut:
    from app.db.models import Event

    target = await session.get(Event, event_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    if body.start_at or body.end_at:
        new_start = body.start_at or target.start_at
        new_end = body.end_at or target.end_at
        if new_end <= new_start:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_at must be after start_at")
        await service.move_event(session, user, event_id=event_id, new_start=new_start, new_end=new_end)
    if body.title is not None or body.description is not None or body.location is not None:
        await service.update_event(
            session,
            user,
            event_id=event_id,
            title=body.title,
            description=body.description,
            location=body.location,
        )
    if body.category is not None:
        await record_correction(session, user, target, body.category)

    await session.refresh(target)
    return target  # type: ignore[return-value]


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: UUID, user: CurrentUser, session: DbSession) -> None:
    await service.delete_event(session, user, event_id=event_id)


@router.post("/sync")
async def sync(
    user: CurrentUser,
    session: DbSession,
    full: Annotated[bool, Query()] = False,
) -> dict[str, int | str]:
    """Sync the user's connected external calendar (Yandex CalDAV) into the DB."""
    try:
        count = await service.sync_user_calendar(session, user, full=full)
    except IntegrationNotConnected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"upserted": count, "status": "ok"}
