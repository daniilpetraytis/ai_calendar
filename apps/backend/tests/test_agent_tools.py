"""Tests for agent calendar tools — conflicts, shifting, resizing and finishing events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent import tools as agent_tools
from app.agent.tools import ProposalSlot, ToolContext, build_tools
from app.db.models import EventSource

def _make_event(*, title, start, end, all_day=False, eid=None, is_movable=True):
    return SimpleNamespace(
        id=eid or uuid4(),
        title=title,
        description=None,
        location=None,
        start_at=start,
        end_at=end,
        is_movable=is_movable,
        priority=0,
        source=EventSource.LOCAL,
        category=None,
        category_source=None,
        all_day=all_day,
    )

def _fake_user(tz="UTC"):
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), timezone=tz, email="t@example.com")

def _get_tool(tools, name):
    return next(t for t in tools if t.name == name)

@pytest.mark.asyncio
async def test_find_conflicts_excludes_self_and_all_day(monkeypatch):
    moved_id = uuid4()
    other_id = uuid4()
    all_day_id = uuid4()

    new_start = datetime(2026, 5, 10, 18, 0, tzinfo=timezone.utc)
    new_end = datetime(2026, 5, 10, 19, 30, tzinfo=timezone.utc)

    moved = _make_event(
        title="Тренировка",
        start=new_start,
        end=new_end,
        eid=moved_id,
    )
    work = _make_event(
        title="Работа",
        start=datetime(2026, 5, 10, 19, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 10, 20, 0, tzinfo=timezone.utc),
        eid=other_id,
    )
    holiday = _make_event(
        title="Праздник",
        start=datetime(2026, 5, 10, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc),
        all_day=True,
        eid=all_day_id,
    )

    async def fake_list_events(_session, _user, *, start, end):
        return [moved, work, holiday]

    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    conflicts = await agent_tools._find_conflicts(
        session=object(),
        user=object(),
        start=new_start,
        end=new_end,
        exclude_id=moved_id,
        tz=timezone.utc,
    )

    titles = [c["title"] for c in conflicts]
    assert titles == ["Работа"], (
        "the moved event itself and all-day events must be filtered out, "
        "leaving only the real overlap"
    )

@pytest.mark.asyncio
async def test_find_conflicts_empty_when_no_overlap(monkeypatch):
    new_start = datetime(2026, 5, 10, 18, 0, tzinfo=timezone.utc)
    new_end = datetime(2026, 5, 10, 19, 30, tzinfo=timezone.utc)

    moved = _make_event(title="Тренировка", start=new_start, end=new_end)

    async def fake_list_events(_session, _user, *, start, end):
        return [moved]

    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    conflicts = await agent_tools._find_conflicts(
        session=object(),
        user=object(),
        start=new_start,
        end=new_end,
        exclude_id=moved.id,
        tz=timezone.utc,
    )
    assert conflicts == []

@pytest.mark.asyncio
async def test_propose_shift_moves_future_movable_only(monkeypatch):
    fixed_now = datetime(2026, 5, 10, 14, 0, tzinfo=timezone.utc)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(agent_tools, "datetime", _DT)

    in_progress = _make_event(
        title="Idет встреча",
        start=fixed_now - timedelta(minutes=30),
        end=fixed_now + timedelta(minutes=30),
    )
    future_movable = _make_event(
        title="Ужин",
        start=fixed_now + timedelta(hours=4),
        end=fixed_now + timedelta(hours=5),
    )
    future_immovable = _make_event(
        title="Самолёт",
        start=fixed_now + timedelta(hours=6),
        end=fixed_now + timedelta(hours=8),
        is_movable=False,
    )
    holiday = _make_event(
        title="Праздник",
        start=fixed_now.replace(hour=0, minute=0),
        end=fixed_now.replace(hour=0, minute=0) + timedelta(days=1),
        all_day=True,
    )

    async def fake_list_events(_session, _user, *, start, end):
        return [in_progress, future_movable, future_immovable, holiday]

    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    user = _fake_user()
    ctx = ToolContext(session=object(), user=user, proposal=ProposalSlot())
    tools = build_tools(ctx)
    propose_shift = _get_tool(tools, "propose_shift")

    result = await propose_shift.coroutine(delta_minutes=15, horizon_days=1)

    assert result["needs_user_approval"] is True
    assert len(result["changes"]) == 1, "only the future movable event should be shifted"
    change = result["changes"][0]
    assert change["op"] == "move"
    assert change["title"] == "Ужин"
    new_start = datetime.fromisoformat(change["new_start_iso"])
    assert new_start == future_movable.start_at + timedelta(minutes=15)

    assert [s["title"] for s in result["skipped_immovable"]] == ["Самолёт"]
    assert [s["title"] for s in result["skipped_already_started"]] == ["Idет встреча"]

    assert ctx.proposal.value is not None
    assert len(ctx.proposal.value.changes) == 1

@pytest.mark.asyncio
async def test_propose_shift_rejects_zero_delta():
    user = _fake_user()
    ctx = ToolContext(session=object(), user=user, proposal=ProposalSlot())
    propose_shift = _get_tool(build_tools(ctx), "propose_shift")
    result = await propose_shift.coroutine(delta_minutes=0)
    assert "error" in result
    assert ctx.proposal.value is None

@pytest.mark.asyncio
async def test_propose_shift_today_horizon_excludes_tomorrow_events(monkeypatch):
    fixed_now = datetime(2026, 5, 10, 18, 15, tzinfo=timezone.utc)  # 21:15 in Europe/Moscow

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(agent_tools, "datetime", _DT)

    today_late = _make_event(
        title="Работа над дипломом",
        start=datetime(2026, 5, 10, 18, 30, tzinfo=timezone.utc),  # 21:30 local
        end=datetime(2026, 5, 10, 19, 45, tzinfo=timezone.utc),    # 22:45 local
    )
    tomorrow_morning = _make_event(
        title="Тренировка с реабилитологом",
        start=datetime(2026, 5, 11, 7, 15, tzinfo=timezone.utc),   # 10:15 local
        end=datetime(2026, 5, 11, 8, 15, tzinfo=timezone.utc),     # 11:15 local
    )

    async def fake_list_events(_session, _user, *, start, end):
        return [e for e in [today_late, tomorrow_morning] if e.end_at > start and e.start_at < end]

    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    user = _fake_user("Europe/Moscow")
    ctx = ToolContext(session=object(), user=user, proposal=ProposalSlot())
    propose_shift = _get_tool(build_tools(ctx), "propose_shift")

    result = await propose_shift.coroutine(delta_minutes=15, horizon_days=1)

    shifted_titles = [c["title"] for c in result["changes"]]
    assert shifted_titles == ["Работа над дипломом"]

@pytest.mark.asyncio
async def test_finish_event_now_and_propose_shift_today(monkeypatch):
    fixed_now = datetime(2026, 5, 10, 18, 15, tzinfo=timezone.utc)  # 21:15 Europe/Moscow

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(agent_tools, "datetime", _DT)

    user = _fake_user("Europe/Moscow")
    training_id = uuid4()
    training = _make_event(
        title="Тренировка",
        start=datetime(2026, 5, 10, 16, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 10, 18, 0, tzinfo=timezone.utc),  # delayed by 15m
        eid=training_id,
    )
    training.user_id = user.id

    during_delay = _make_event(
        title="Ужин",
        start=datetime(2026, 5, 10, 18, 5, tzinfo=timezone.utc),   # starts after original end
        end=datetime(2026, 5, 10, 18, 35, tzinfo=timezone.utc),
    )
    today_future = _make_event(
        title="Работа над дипломом",
        start=datetime(2026, 5, 10, 18, 30, tzinfo=timezone.utc),
        end=datetime(2026, 5, 10, 19, 30, tzinfo=timezone.utc),
    )
    tomorrow_future = _make_event(
        title="Тренировка с реабилитологом",
        start=datetime(2026, 5, 11, 7, 15, tzinfo=timezone.utc),
        end=datetime(2026, 5, 11, 8, 15, tzinfo=timezone.utc),
    )

    captured = {}

    async def fake_move_event(_session, _user, *, event_id, new_start, new_end):
        captured["event_id"] = event_id
        captured["new_start"] = new_start
        captured["new_end"] = new_end
        training.start_at = new_start
        training.end_at = new_end
        return training

    async def fake_list_events(_session, _user, *, start, end):
        pool = [training, during_delay, today_future, tomorrow_future]
        return [e for e in pool if e.end_at > start and e.start_at < end]

    monkeypatch.setattr(agent_tools.cal_service, "move_event", fake_move_event)
    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    ctx = ToolContext(session=_FakeSession(training), user=user, proposal=ProposalSlot())
    tool = _get_tool(build_tools(ctx), "finish_event_now_and_propose_shift_today")
    result = await tool.coroutine(event_id=str(training_id))

    assert captured["event_id"] == training_id
    assert captured["new_start"] == datetime(2026, 5, 10, 16, 0, tzinfo=timezone.utc)
    assert captured["new_end"] == fixed_now
    assert result["delay_minutes"] == 15
    assert [c["title"] for c in result["changes"]] == ["Ужин", "Работа над дипломом"]
    assert result["needs_user_approval"] is True
    assert ctx.proposal.value is not None
    assert len(ctx.proposal.value.changes) == 2

class _FakeSession:

    def __init__(self, event):
        self._event = event

    async def get(self, _model, _eid):
        return self._event

@pytest.mark.asyncio
async def test_shift_event_preserves_duration(monkeypatch):
    user = _fake_user()
    eid = uuid4()
    start = datetime(2026, 5, 10, 18, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 10, 19, 30, tzinfo=timezone.utc)
    event = _make_event(title="Тренировка", start=start, end=end, eid=eid)
    event.user_id = user.id

    captured = {}

    async def fake_move_event(_session, _user, *, event_id, new_start, new_end):
        captured["event_id"] = event_id
        captured["new_start"] = new_start
        captured["new_end"] = new_end
        event.start_at = new_start
        event.end_at = new_end
        return event

    async def fake_list_events(_session, _user, *, start, end):
        return [event]

    monkeypatch.setattr(agent_tools.cal_service, "move_event", fake_move_event)
    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    ctx = ToolContext(session=_FakeSession(event), user=user, proposal=ProposalSlot())
    shift_event = _get_tool(build_tools(ctx), "shift_event")

    result = await shift_event.coroutine(event_id=str(eid), delta_minutes=15)

    assert captured["new_start"] == start + timedelta(minutes=15)
    assert captured["new_end"] == end + timedelta(minutes=15)
    new_duration = captured["new_end"] - captured["new_start"]
    assert new_duration == end - start, "shift must preserve duration"
    assert result["delta_minutes"] == 15
    assert result["conflicts"] == []

@pytest.mark.asyncio
async def test_resize_event_only_moves_end(monkeypatch):
    user = _fake_user()
    eid = uuid4()
    start = datetime(2026, 5, 10, 19, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 10, 20, 0, tzinfo=timezone.utc)
    event = _make_event(title="Ужин", start=start, end=end, eid=eid)
    event.user_id = user.id

    captured = {}

    async def fake_move_event(_session, _user, *, event_id, new_start, new_end):
        captured["new_start"] = new_start
        captured["new_end"] = new_end
        event.start_at = new_start
        event.end_at = new_end
        return event

    async def fake_list_events(_session, _user, *, start, end):
        return [event]

    monkeypatch.setattr(agent_tools.cal_service, "move_event", fake_move_event)
    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    ctx = ToolContext(session=_FakeSession(event), user=user, proposal=ProposalSlot())
    resize_event = _get_tool(build_tools(ctx), "resize_event")

    result = await resize_event.coroutine(event_id=str(eid), end_delta_minutes=15)

    assert captured["new_start"] == start, "start must NOT move"
    assert captured["new_end"] == end + timedelta(minutes=15)
    assert result["end_delta_minutes"] == 15

@pytest.mark.asyncio
async def test_resize_event_refuses_collapse_or_negative():
    user = _fake_user()
    eid = uuid4()
    start = datetime(2026, 5, 10, 19, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 10, 19, 30, tzinfo=timezone.utc)
    event = _make_event(title="Ужин", start=start, end=end, eid=eid)
    event.user_id = user.id

    ctx = ToolContext(session=_FakeSession(event), user=user, proposal=ProposalSlot())
    resize_event = _get_tool(build_tools(ctx), "resize_event")

    # Shortening by more than the event's length is meaningless.
    result = await resize_event.coroutine(event_id=str(eid), end_delta_minutes=-60)
    assert "error" in result

    result = await resize_event.coroutine(event_id=str(eid), end_delta_minutes=0)
    assert "error" in result
