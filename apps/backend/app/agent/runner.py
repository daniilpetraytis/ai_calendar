"""Streaming runner for the LangGraph calendar agent — wires the LLM, tools, and persistence layer and yields incremental SSE-friendly events."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_agent
from app.agent.prompts import PlaceHint, build_system_prompt
from app.agent.tools import ProposalSlot, ToolContext, build_tools
from app.config import get_settings
from app.db.models import AgentRun, AgentRunStatus, User
from app.places.service import list_places as list_user_places

log = logging.getLogger(__name__)

def _parse_tool_payload(content):
    """Best-effort decode of a ToolMessage payload into a dict (JSON, then literal_eval, then typed-chunk text)."""
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
    if isinstance(content, list):
        # Some providers encode content as typed chunks.
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return _parse_tool_payload("".join(parts))
    return None

def _hhmm(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except Exception:
        return iso

def _build_write_confirmation(tool_name, payload):
    """Render a deterministic Russian confirmation line for single-event move/shift/resize results."""
    if tool_name not in {"move_event", "shift_event", "resize_event"}:
        return None
    updated = payload.get("updated_event")
    if not isinstance(updated, dict):
        return None

    title = updated.get("title") or "Событие"
    start_hhmm = _hhmm(updated.get("start_iso"))
    end_hhmm = _hhmm(updated.get("end_iso"))
    if start_hhmm and end_hhmm:
        base = f"«{title}» перенесено на {start_hhmm}–{end_hhmm}."
    else:
        base = f"«{title}» перенесено."

    conflicts = payload.get("conflicts")
    if not isinstance(conflicts, list):
        return base
    if not conflicts:
        return f"{base} Конфликтов нет."

    conflict_parts = []
    for c in conflicts:
        if not isinstance(c, dict):
            continue
        c_title = c.get("title") or "Событие"
        c_start = _hhmm(c.get("start_iso"))
        c_end = _hhmm(c.get("end_iso"))
        if c_start and c_end:
            conflict_parts.append(f"«{c_title}» ({c_start}–{c_end})")
        else:
            conflict_parts.append(f"«{c_title}»")
    if conflict_parts:
        return f"{base} Есть конфликты: {', '.join(conflict_parts)}."
    return base

@dataclass(slots=True)
class AgentEvent:
    """A single event yielded from the agent stream, ready to be serialized to SSE."""

    type: str  # "token" | "tool_start" | "tool_end" | "proposal" | "final" | "error"
    payload: dict[str, Any]

def _proposal_to_payload(slot):
    """Convert a scheduler proposal slot into the JSON-serialisable payload sent to clients."""
    if slot.value is None:
        return None
    p = slot.value
    if not p.changes:
        return None
    return {
        "summary": p.summary,
        "changes": [
            {
                "op": c.op,
                "kind": c.item.kind,
                "id": str(c.item.id),
                "title": c.item.title,
                "new_start_iso": c.new_start.isoformat() if c.new_start else None,
                "new_end_iso": c.new_end.isoformat() if c.new_end else None,
                "reason": c.reason,
            }
            for c in p.changes
        ],
        "unscheduled": [
            {"id": str(u.id), "kind": u.kind, "title": u.title} for u in p.unscheduled
        ],
    }

async def run_agent_stream(
    *,
    session,
    user,
    user_message,
    thread_id = None,
):
    """Run one turn of the calendar agent and yield ``AgentEvent`` items as they arrive.

    Persists an ``AgentRun`` row, streams LLM tokens and tool calls, and emits a
    final ``proposal`` event when the run produced a multi-change proposal that
    needs user approval. Aborts with an ``error`` event if no progress happens
    within ``settings.agent_total_timeout_seconds``."""
    thread_id = thread_id or f"thread-{uuid.uuid4().hex[:12]}"

    run = AgentRun(
        tenant_id=user.tenant_id,
        user_id=user.id,
        thread_id=thread_id,
        status=AgentRunStatus.RUNNING,
        user_message=user_message,
    )
    session.add(run)
    await session.flush()

    yield AgentEvent("run_started", {"run_id": str(run.id), "thread_id": thread_id})

    settings = get_settings()
    ctx = ToolContext(session=session, user=user)
    tools = build_tools(ctx)
    saved_places = await list_user_places(session, user)
    place_hints = [
        PlaceHint(name=p.name, address=p.address, is_default=p.is_default)
        for p in saved_places
    ]
    system_prompt = build_system_prompt(
        email=user.email,
        tz_name=user.timezone or "UTC",
        places=place_hints,
    )
    agent = build_agent(tools, system_prompt)

    final_text_parts = []
    last_tool_name = None
    last_tool_payload = None

    async def _consume():
        nonlocal last_tool_name, last_tool_payload
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content=user_message)]},
            stream_mode="messages",
            config={"recursion_limit": settings.agent_recursion_limit},
        ):
            if isinstance(chunk, tuple):
                msg = chunk[0]
            else:
                msg = chunk
            if isinstance(msg, AIMessageChunk):
                if msg.content:
                    if isinstance(msg.content, str):
                        text = msg.content
                    else:
                        text = "".join(
                            part.get("text", "")
                            for part in msg.content
                            if isinstance(part, dict) and part.get("type") == "text"
                        )
                    if text:
                        final_text_parts.append(text)
                        yield AgentEvent("token", {"text": text})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        yield AgentEvent(
                            "tool_start",
                            {"name": tc.get("name"), "args": tc.get("args", {})},
                        )
            elif isinstance(msg, ToolMessage):
                parsed_payload = _parse_tool_payload(msg.content)
                if msg.name and parsed_payload is not None:
                    last_tool_name = msg.name
                    last_tool_payload = parsed_payload
                yield AgentEvent(
                    "tool_end",
                    {"name": msg.name, "ok": msg.status != "error"},
                )
            elif isinstance(msg, AIMessage):
                pass

    iterator = _consume().__aiter__()
    try:
        while True:
            try:
                evt = await asyncio.wait_for(
                    iterator.__anext__(),
                    timeout=settings.agent_total_timeout_seconds,
                )
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                msg = (
                    f"Agent timed out after {settings.agent_total_timeout_seconds:.0f}s "
                    "with no progress. Please try again."
                )
                log.warning("agent stream stalled, aborting", extra={"thread_id": thread_id})
                run.status = AgentRunStatus.FAILED
                run.error = msg
                yield AgentEvent("error", {"message": msg})
                return
            yield evt
    except Exception as exc:
        run.status = AgentRunStatus.FAILED
        run.error = str(exc)
        yield AgentEvent("error", {"message": str(exc)})
        return

    final_text = "".join(final_text_parts).strip()

    proposal_payload = _proposal_to_payload(ctx.proposal)
    if proposal_payload is not None:
        run.status = AgentRunStatus.AWAITING_APPROVAL
        run.proposal = proposal_payload
        yield AgentEvent(
            "proposal",
            {"run_id": str(run.id), "proposal": proposal_payload},
        )
    else:
        deterministic = (
            _build_write_confirmation(last_tool_name, last_tool_payload)
            if last_tool_name and last_tool_payload
            else None
        )
        if deterministic:
            final_text = deterministic
        run.status = AgentRunStatus.COMPLETED
    run.assistant_message = final_text

    yield AgentEvent(
        "final",
        {
            "run_id": str(run.id),
            "thread_id": thread_id,
            "status": run.status.value,
            "message": final_text,
        },
    )

def event_to_sse(evt):
    """Adapt an ``AgentEvent`` to the ``{event, data}`` shape expected by Starlette's EventSourceResponse."""
    return {"event": evt.type, "data": json.dumps(evt.payload)}
