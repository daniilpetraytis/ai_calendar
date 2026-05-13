"""CRUD endpoints for the user's saved places (home, office, etc.)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy import update as sa_update

from app.api.schemas import PlaceCreate, PlaceOut, PlaceUpdate
from app.db.models import Place
from app.deps import CurrentUser, DbSession

router = APIRouter()

async def _clear_other_defaults(session: DbSession, user, *, keep_id: UUID | None) -> None:
    """Unset ``is_default`` on all places except the one being kept."""
    stmt = sa_update(Place).where(
        and_(Place.user_id == user.id, Place.is_default.is_(True))
    )
    if keep_id is not None:
        stmt = stmt.where(Place.id != keep_id)
    stmt = stmt.values(is_default=False)
    await session.execute(stmt)

@router.get("", response_model=list[PlaceOut])
async def list_places(user: CurrentUser, session: DbSession) -> list[Place]:
    """List the user's saved places, default first then alphabetical."""
    rows = await session.execute(
        select(Place)
        .where(Place.user_id == user.id)
        .order_by(Place.is_default.desc(), Place.name.asc())
    )
    return list(rows.scalars().all())

@router.post("", response_model=PlaceOut, status_code=status.HTTP_201_CREATED)
async def create_place(
    body: PlaceCreate, user: CurrentUser, session: DbSession
) -> Place:
    """Create a new saved place; promotes it as the sole default if requested."""
    name = body.name.strip()
    address = body.address.strip()
    existing = (
        await session.execute(
            select(Place).where(
                and_(Place.user_id == user.id, Place.name == name)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Place '{name}' already exists.",
        )

    place = Place(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=name,
        address=address,
        is_default=body.is_default,
    )
    session.add(place)
    await session.flush()
    if body.is_default:
        await _clear_other_defaults(session, user, keep_id=place.id)
    return place

@router.patch("/{place_id}", response_model=PlaceOut)
async def update_place(
    place_id: UUID,
    body: PlaceUpdate,
    user: CurrentUser,
    session: DbSession,
) -> Place:
    """Update an existing place, enforcing name uniqueness and a single default."""
    place = await session.get(Place, place_id)
    if place is None or place.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Place not found")
    if body.name is not None:
        new_name = body.name.strip()
        if new_name != place.name:
            clash = (
                await session.execute(
                    select(Place).where(
                        and_(
                            Place.user_id == user.id,
                            Place.name == new_name,
                            Place.id != place.id,
                        )
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Place '{new_name}' already exists.",
                )
            place.name = new_name
    if body.address is not None:
        place.address = body.address.strip()
    if body.is_default is not None:
        place.is_default = body.is_default
        if body.is_default:
            await _clear_other_defaults(session, user, keep_id=place.id)
    await session.flush()
    return place

@router.delete("/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_place(
    place_id: UUID, user: CurrentUser, session: DbSession
) -> None:
    """Delete one of the user's saved places."""
    place = await session.get(Place, place_id)
    if place is None or place.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Place not found")
    await session.delete(place)
