"""Event categorization service: rules + LLM classification and user corrections."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.categorize import DEFAULT_CATEGORIES
from app.categorize.rules import classify_by_rules
from app.db.models import (
    CategoryCorrection,
    CategoryDefinition,
    CategorySource,
    Event,
    User,
)

log = logging.getLogger(__name__)

async def seed_default_categories(session, user):
    """Insert the default category catalog for a user if they have none yet."""
    existing = (
        await session.execute(
            select(CategoryDefinition).where(CategoryDefinition.user_id == user.id).limit(1)
        )
    ).scalar_one_or_none()

    if existing is not None:
        return  # already seeded

    for cat in DEFAULT_CATEGORIES:
        session.add(
            CategoryDefinition(
                tenant_id=user.tenant_id,
                user_id=user.id,
                name=cat["name"],
                color=cat["color"],
                emoji=cat.get("emoji"),
                is_default=True,
            )
        )
    await session.flush()
    log.info("categories_seeded", extra={"user_id": str(user.id)})

async def get_user_categories(
    session, user
):
    """Return all category definitions for the user, seeding defaults if missing."""
    await seed_default_categories(session, user)
    rows = (
        await session.execute(
            select(CategoryDefinition)
            .where(CategoryDefinition.user_id == user.id)
            .order_by(CategoryDefinition.name)
        )
    ).scalars().all()
    return list(rows)

def _apply_category(
    event, category, source, confidence
):
    """Mutate an event in place with the new category, source, and confidence."""
    event.category = category
    event.category_source = source
    event.category_confidence = confidence

def classify_event_by_rules(event):
    """Apply the rule-based classifier to an event and return whether a category was assigned."""
    if event.category_source == CategorySource.USER:
        return False

    result = classify_by_rules(
        event.title,
        event.description,
        event.location,
        event.start_at,
        event.end_at,
    )
    if result is None:
        return False

    category, confidence = result
    _apply_category(event, category, CategorySource.RULES, confidence)
    return True

async def classify_pending_llm(
    session, user, limit = 200
):
    """Classify uncategorized events for a user via the LLM and return the number labelled."""
    rows = (
        await session.execute(
            select(Event)
            .where(
                and_(
                    Event.user_id == user.id,
                    Event.category.is_(None),
                )
            )
            .order_by(Event.start_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    events = list(rows)
    if not events:
        return 0

    from app.categorize.llm import classify_with_llm

    predictions = await classify_with_llm(events)

    id_map = {e.id: e for e in events}
    classified = 0
    for event_id, (category, confidence) in predictions.items():
        ev = id_map.get(event_id)
        if ev is None:
            continue
        _apply_category(ev, category, CategorySource.LLM, confidence)
        classified += 1

    if classified:
        await session.flush()
        log.info(
            "llm_classified",
            extra={"user_id": str(user.id), "count": classified},
        )
    return classified

async def record_correction(
    session,
    user,
    event,
    new_category,
):
    """Persist a user correction of an event's category and update the event accordingly."""
    if event.category == new_category and event.category_source == CategorySource.USER:
        return

    correction = CategoryCorrection(
        id=uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        event_id=event.id,
        event_title=event.title,
        event_description=event.description,
        event_location=event.location,
        predicted=event.category,
        predicted_source=event.category_source,
        predicted_confidence=event.category_confidence,
        corrected=new_category,
        created_at=datetime.now(timezone.utc),
    )
    session.add(correction)

    _apply_category(event, new_category, CategorySource.USER, 1.0)
    await session.flush()
