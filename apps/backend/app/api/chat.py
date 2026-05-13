"""Chat endpoint with SSE streaming."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sse_starlette.sse import EventSourceResponse

from app.agent.runner import event_to_sse, run_agent_stream
from app.api.schemas import ChatMessage
from app.auth import AuthPrincipal, get_principal
from app.auth.users import resolve_or_create_user
from app.db import get_sessionmaker

router = APIRouter()

@router.post("")
async def chat(
    body: ChatMessage,
    principal: Annotated[AuthPrincipal, Depends(get_principal)],
    user_timezone: Annotated[str | None, Header(alias="X-User-Timezone")] = None,
):
    """Stream the agent's response to a user chat message as SSE events."""
    sm = get_sessionmaker()

    async def event_gen():
        async with sm() as session:
            try:
                user = await resolve_or_create_user(session, principal, timezone=user_timezone)
                async for evt in run_agent_stream(
                    session=session,
                    user=user,
                    user_message=body.message,
                    thread_id=body.thread_id,
                ):
                    yield event_to_sse(evt)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return EventSourceResponse(event_gen())
