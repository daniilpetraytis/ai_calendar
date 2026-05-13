"""Per-user category CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, select

from app.api.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from app.categorize import VALID_CATEGORIES
from app.categorize.service import get_user_categories
from app.db.models import CategoryDefinition
from app.deps import CurrentUser, DbSession

router = APIRouter()

@router.get("", response_model=list[CategoryOut])
async def list_categories(user: CurrentUser, session: DbSession):
    """List all categories defined for the current user."""
    cats = await get_user_categories(session, user)
    return cats

@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryCreate, user: CurrentUser, session: DbSession
) -> CategoryOut:
    """Create a new custom category for the current user."""
    name = body.name.lower().strip()
    existing = (
        await session.execute(
            select(CategoryDefinition).where(
                and_(
                    CategoryDefinition.user_id == user.id,
                    CategoryDefinition.name == name,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Category '{name}' already exists")

    cat = CategoryDefinition(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=name,
        color=body.color,
        emoji=body.emoji,
        goal_minutes_per_week=body.goal_minutes_per_week,
        is_default=False,
    )
    session.add(cat)
    await session.flush()
    return cat  # type: ignore[return-value]

@router.patch("/{name}", response_model=CategoryOut)
async def update_category(
    name: str, body: CategoryUpdate, user: CurrentUser, session: DbSession
) -> CategoryOut:
    """Update color, emoji or weekly goal for an existing category."""
    cat = (
        await session.execute(
            select(CategoryDefinition).where(
                and_(
                    CategoryDefinition.user_id == user.id,
                    CategoryDefinition.name == name,
                )
            )
        )
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Category '{name}' not found")

    if body.color is not None:
        cat.color = body.color
    if body.emoji is not None:
        cat.emoji = body.emoji
    # Allow clearing goal by passing 0 or null explicitly
    if "goal_minutes_per_week" in body.model_fields_set:
        cat.goal_minutes_per_week = body.goal_minutes_per_week

    await session.flush()
    return cat  # type: ignore[return-value]

@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(name: str, user: CurrentUser, session: DbSession) -> None:
    """Delete a custom category and clear its references on existing events."""
    cat = (
        await session.execute(
            select(CategoryDefinition).where(
                and_(
                    CategoryDefinition.user_id == user.id,
                    CategoryDefinition.name == name,
                )
            )
        )
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Category '{name}' not found")
    if cat.is_default:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Default categories cannot be deleted. Update color/goal instead.",
        )

    from sqlalchemy import update as sa_update

    from app.db.models import Event

    await session.execute(
        sa_update(Event)
        .where(and_(Event.user_id == user.id, Event.category == name))
        .values(category=None, category_source=None, category_confidence=None)
    )

    await session.delete(cat)
