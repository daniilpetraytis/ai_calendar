"""Endpoints for inspecting and applying agent replan proposals."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from dateutil import parser as dateparser
from fastapi import APIRouter, HTTPException, status

from app.api.schemas import ReplanDecision, ReplanProposal
from app.calendar import service as cal_service
from app.db.models import AgentRun, AgentRunStatus, Task, TaskStatus
from app.deps import CurrentUser, DbSession

router = APIRouter()

@router.get("/{run_id}", response_model=ReplanProposal)
async def get_proposal(run_id: UUID, user: CurrentUser, session: DbSession) -> ReplanProposal:
    """Return the pending replan proposal produced by an agent run."""
    run = await session.get(AgentRun, run_id)
    if run is None or run.user_id != user.id or run.proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return ReplanProposal(summary=run.proposal.get("summary", ""), changes=run.proposal.get("changes", []))

@router.post("/{run_id}/apply")
async def apply_proposal(
    run_id: UUID,
    decision: ReplanDecision,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, object]:
    """Apply (or reject) a previously generated replan proposal."""
    run = await session.get(AgentRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if run.status != AgentRunStatus.AWAITING_APPROVAL or run.proposal is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Run is not awaiting approval")

    if not decision.approve:
        run.status = AgentRunStatus.REJECTED
        return {"status": "rejected", "applied": 0}

    changes: list[dict] = list(run.proposal.get("changes", []))
    accepted_idx = (
        set(decision.accepted_indices)
        if decision.accepted_indices is not None
        else set(range(len(changes)))
    )

    applied = 0
    errors: list[dict[str, str]] = []
    for i, change in enumerate(changes):
        if i not in accepted_idx:
            continue
        try:
            await _apply_change(session, user, change)
            applied += 1
        except Exception as exc:
            errors.append({"index": str(i), "error": str(exc), "title": change.get("title", "")})

    run.status = AgentRunStatus.COMPLETED
    return {"status": "applied", "applied": applied, "errors": errors}

async def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string, returning None for empty input."""
    return dateparser.isoparse(value) if value else None

async def _apply_change(session, user, change: dict) -> None:
    """Apply a single proposed change (move/create/delete/skip) to the calendar."""
    op = change["op"]
    kind = change.get("kind")
    new_start = await _parse_dt(change.get("new_start_iso"))
    new_end = await _parse_dt(change.get("new_end_iso"))
    title = change.get("title", "Task")
    item_id_raw = change.get("id")

    if op == "skip":
        return

    if op == "move":
        if not item_id_raw or not new_start or not new_end:
            raise ValueError("move requires id, new_start_iso, new_end_iso")
        await cal_service.move_event(
            session,
            user,
            event_id=UUID(item_id_raw),
            new_start=new_start,
            new_end=new_end,
        )
        return

    if op == "create":
        if not new_start or not new_end:
            raise ValueError("create requires new_start_iso and new_end_iso")
        event = await cal_service.create_event(
            session, user, title=title, start=new_start, end=new_end
        )
        if kind == "task" and item_id_raw:
            task = await session.get(Task, UUID(item_id_raw))
            if task is not None and task.user_id == user.id:
                task.status = TaskStatus.SCHEDULED
                task.scheduled_event_id = event.id
        return

    if op == "delete":
        if not item_id_raw:
            raise ValueError("delete requires id")
        await cal_service.delete_event(session, user, event_id=UUID(item_id_raw))
        return

    raise ValueError(f"Unknown op: {op}")
