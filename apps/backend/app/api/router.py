"""Top-level API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    biometrics,
    categories,
    chat,
    events,
    health,
    integrations,
    me,
    places,
    replan,
    scheduler,
    stats,
    tasks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(replan.router, prefix="/replan", tags=["replan"])
api_router.include_router(
    scheduler.router, prefix="/scheduler", tags=["scheduler"]
)
api_router.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
api_router.include_router(
    biometrics.router, prefix="/biometrics", tags=["biometrics"]
)
api_router.include_router(places.router, prefix="/places", tags=["places"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
