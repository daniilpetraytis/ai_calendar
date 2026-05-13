"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.logging_setup import setup_logging

@asynccontextmanager
async def lifespan(app):  # noqa: ARG001
    """Application lifespan hook — initialises logging on startup."""
    setup_logging()
    yield

def create_app():
    """Build and return the FastAPI application with middleware and routers wired up."""
    settings = get_settings()
    app = FastAPI(
        title="AI Calendar API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")
    return app

app = create_app()
