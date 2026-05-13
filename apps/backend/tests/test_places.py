"""Tests for the places service and place-aware agent calendar tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import unquote
from uuid import uuid4

import pytest

from app.agent import tools as agent_tools
from app.agent.tools import ProposalSlot, ToolContext, build_tools
from app.db.models import EventSource
from app.places import service as places_service
from app.places.service import (
    DEFAULT_ROUTE_MODE,
    append_route_to_description,
    build_yandex_route_url,
)

def _make_event(
    *,
    title,
    start,
    end,
    all_day=False,
    eid=None,
    is_movable=True,
    location=None,
    description=None,
):
    return SimpleNamespace(
        id=eid or uuid4(),
        title=title,
        description=description,
        location=location,
        start_at=start,
        end_at=end,
        is_movable=is_movable,
        priority=0,
        source=EventSource.LOCAL,
        category=None,
        category_source=None,
        all_day=all_day,
        user_id=None,
    )

def _fake_user(tz="UTC"):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        timezone=tz,
        email="t@example.com",
    )

def _make_place(*, name, address, is_default=False, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        address=address,
        is_default=is_default,
        user_id=user_id,
        tenant_id=uuid4(),
    )

def _get_tool(tools, name):
    return next(t for t in tools if t.name == name)

def test_build_yandex_route_url_uses_mt_by_default_and_encodes_addresses():
    url = build_yandex_route_url("Москва, Тверская 1", "Москва, Арбат 10")
    assert url.startswith("https://yandex.ru/maps/?rtext=")
    assert f"rtt={DEFAULT_ROUTE_MODE}" in url
    # The literal `~` separator must NOT be encoded.
    assert "~" in url
    # Both addresses survive a roundtrip through URL-decode.
    payload = url.split("rtext=", 1)[1].split("&", 1)[0]
    left, right = payload.split("~")
    assert unquote(left) == "Москва, Тверская 1"
    assert unquote(right) == "Москва, Арбат 10"

def test_build_yandex_route_url_falls_back_to_default_mode_on_unknown_mode():
    url = build_yandex_route_url("A", "B", mode="hyperloop")
    assert f"rtt={DEFAULT_ROUTE_MODE}" in url

def test_append_route_appends_when_marker_absent():
    out = append_route_to_description("Существующее описание", "https://example/route")
    assert "Существующее описание" in out
    assert "Маршрут: https://example/route" in out
    assert out.count("Маршрут: ") == 1

def test_append_route_is_idempotent_when_marker_present():
    first = append_route_to_description(None, "https://example/old")
    second = append_route_to_description(first, "https://example/new")
    assert second.count("Маршрут: ") == 1, "second call must replace, not stack"
    assert "https://example/new" in second
    assert "https://example/old" not in second

def test_append_route_to_empty_description_creates_single_line():
    out = append_route_to_description(None, "https://example/route")
    assert out == "Маршрут: https://example/route"

class _FakeScalarResult:

    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

class _FakeSession:

    def __init__(self, *, places=None, events=None, get_map=None):
        self._places = list(places or [])
        self._events = list(events or [])
        self._get_map = dict(get_map or {})
        self.deleted = []
        self.added = []

    async def execute(self, stmt):
        from app.db.models import Event, Place

        target = stmt.column_descriptions[0]["type"]
        if target is Place:
            return _FakeScalarResult(self._places)
        if target is Event:
            return _FakeScalarResult(self._events)
        return _FakeScalarResult([])

    async def get(self, model, key):
        return self._get_map.get(key)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def delete(self, obj):
        self.deleted.append(obj)

@pytest.mark.asyncio
async def test_resolve_place_exact_match_case_insensitive():
    user = _fake_user()
    rows = [
        _make_place(name="Дом", address="ул. Тверская 1", is_default=True, user_id=user.id),
        _make_place(name="Офис", address="ул. Арбат 10", user_id=user.id),
    ]
    session = _FakeSession(places=rows)
    out = await places_service.resolve_place_by_name(session, user, "дом")
    assert out is not None and out.name == "Дом"

@pytest.mark.asyncio
async def test_resolve_place_unique_prefix_match():
    user = _fake_user()
    rows = [
        _make_place(name="Парикмахерская", address="ул. Тверская 5", user_id=user.id),
        _make_place(name="Офис", address="ул. Арбат 10", user_id=user.id),
    ]
    session = _FakeSession(places=rows)
    out = await places_service.resolve_place_by_name(session, user, "парикма")
    assert out is not None and out.name == "Парикмахерская"

@pytest.mark.asyncio
async def test_resolve_place_returns_none_on_ambiguous_prefix():
    user = _fake_user()
    rows = [
        _make_place(name="Парикмахерская у Маши", address="A", user_id=user.id),
        _make_place(name="Парикмахерская на Тверской", address="B", user_id=user.id),
    ]
    session = _FakeSession(places=rows)
    assert await places_service.resolve_place_by_name(session, user, "парикма") is None

@pytest.mark.asyncio
async def test_find_previous_event_location_returns_most_recent_with_location():
    user = _fake_user()
    target_start = datetime(2026, 5, 12, 15, 0, tzinfo=UTC)
    rows_desc = [
        _make_event(
            title="Без локации",
            start=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
            end=datetime(2026, 5, 12, 12, 30, tzinfo=UTC),
            location="",  # filtered by the loop
        ),
        _make_event(
            title="Завтрак",
            start=datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
            end=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
            location="ул. Тверская 1",
        ),
    ]
    session = _FakeSession(events=rows_desc)
    out = await places_service.find_previous_event_location(
        session,
        user,
        target_start=target_start,
        tz=UTC,
    )
    assert out == "ул. Тверская 1"

@pytest.mark.asyncio
async def test_create_event_with_place_name_fills_location_and_route(monkeypatch):
    user = _fake_user("Europe/Moscow")
    office = _make_place(
        name="Офис",
        address="Москва, Арбат 10",
        user_id=user.id,
    )
    home = _make_place(
        name="Дом",
        address="Москва, Тверская 1",
        is_default=True,
        user_id=user.id,
    )

    captured_create = {}

    async def fake_resolve(_session, _user, name):
        return office if name.lower().startswith("офис") else None

    async def fake_origin(_session, _user, *, target_start, tz, exclude_event_id=None):
        return home.address

    async def fake_create_event(_session, _user, **kwargs):
        captured_create.update(kwargs)
        created = _make_event(
            title=kwargs["title"],
            start=kwargs["start"],
            end=kwargs["end"],
            location=kwargs.get("location"),
            description=kwargs.get("description"),
        )
        created.user_id = user.id
        return created

    async def fake_list_events(_session, _user, *, start, end):
        return []

    monkeypatch.setattr(agent_tools.places_service, "resolve_place_by_name", fake_resolve)
    monkeypatch.setattr(agent_tools, "_resolve_origin_address", fake_origin)
    monkeypatch.setattr(agent_tools.cal_service, "create_event", fake_create_event)
    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    ctx = ToolContext(session=object(), user=user, proposal=ProposalSlot())
    tools = build_tools(ctx)
    create_event = _get_tool(tools, "create_event")

    result = await create_event.coroutine(
        title="Встреча",
        start_iso="2026-05-12T15:00:00+03:00",
        end_iso="2026-05-12T16:00:00+03:00",
        place_name="офис",
    )

    assert captured_create["location"] == office.address
    desc = captured_create["description"]
    assert desc is not None and "Маршрут: https://yandex.ru/maps/?rtext=" in desc
    decoded = unquote(desc)
    assert "Тверская" in decoded and "Арбат" in decoded
    assert "place_lookup_failed" not in result

@pytest.mark.asyncio
async def test_create_event_reports_when_place_name_unknown(monkeypatch):
    user = _fake_user("Europe/Moscow")

    async def fake_resolve(_session, _user, name):
        return None

    async def fake_create_event(_session, _user, **kwargs):
        created = _make_event(
            title=kwargs["title"],
            start=kwargs["start"],
            end=kwargs["end"],
            location=kwargs.get("location"),
        )
        created.user_id = user.id
        return created

    async def fake_list_events(_session, _user, *, start, end):
        return []

    monkeypatch.setattr(agent_tools.places_service, "resolve_place_by_name", fake_resolve)
    monkeypatch.setattr(agent_tools.cal_service, "create_event", fake_create_event)
    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    ctx = ToolContext(session=object(), user=user, proposal=ProposalSlot())
    create_event = _get_tool(build_tools(ctx), "create_event")
    result = await create_event.coroutine(
        title="Встреча",
        start_iso="2026-05-12T15:00:00+03:00",
        end_iso="2026-05-12T16:00:00+03:00",
        place_name="неизвестное_место",
    )
    assert result.get("place_lookup_failed") == "неизвестное_место"
    assert result["created_event"]["location"] is None

@pytest.mark.asyncio
async def test_create_commute_event_title_is_always_doroga(monkeypatch):
    user = _fake_user("Europe/Moscow")
    target_id = uuid4()
    target = _make_event(
        title="Стрижка",
        start=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
        end=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        eid=target_id,
        location="Москва, Барбершоп 3",
    )
    target.user_id = user.id

    captured = {}

    async def fake_origin(_session, _user, *, target_start, tz, exclude_event_id=None):
        return "Москва, Тверская 1"

    async def fake_create_event(_session, _user, **kwargs):
        captured.update(kwargs)
        created = _make_event(
            title=kwargs["title"],
            start=kwargs["start"],
            end=kwargs["end"],
            location=kwargs.get("location"),
            description=kwargs.get("description"),
        )
        created.user_id = user.id
        return created

    async def fake_list_events(_session, _user, *, start, end):
        return []

    monkeypatch.setattr(agent_tools, "_resolve_origin_address", fake_origin)
    monkeypatch.setattr(agent_tools.cal_service, "create_event", fake_create_event)
    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    ctx = ToolContext(
        session=_FakeSession(get_map={target_id: target}),
        user=user,
        proposal=ProposalSlot(),
    )
    tool = _get_tool(build_tools(ctx), "create_commute_event")

    result = await tool.coroutine(
        target_event_id=str(target_id),
        duration_minutes=30,
    )

    assert captured["title"] == "Дорога", (
        "the commute event title must be EXACTLY «Дорога», never «Дорога до X»"
    )
    assert captured["start"] == target.start_at - timedelta(minutes=30)
    assert captured["end"] == target.start_at
    desc = captured["description"]
    assert desc is not None and desc.startswith("https://yandex.ru/maps/?rtext=")
    decoded = unquote(desc)
    assert "Тверская" in decoded and "Барбершоп" in decoded
    assert result["origin"] == "Москва, Тверская 1"
    assert result["destination"] == "Москва, Барбершоп 3"
    assert result["created_event"]["title"] == "Дорога"

@pytest.mark.asyncio
async def test_create_commute_event_works_without_destination(monkeypatch):
    user = _fake_user("Europe/Moscow")
    target_id = uuid4()
    target = _make_event(
        title="Встреча",
        start=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
        end=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        eid=target_id,
        location=None,
    )
    target.user_id = user.id

    captured = {}

    async def fake_origin(_session, _user, *, target_start, tz, exclude_event_id=None):
        return "Москва, Тверская 1"

    async def fake_create_event(_session, _user, **kwargs):
        captured.update(kwargs)
        created = _make_event(
            title=kwargs["title"],
            start=kwargs["start"],
            end=kwargs["end"],
            location=kwargs.get("location"),
            description=kwargs.get("description"),
        )
        created.user_id = user.id
        return created

    async def fake_list_events(_session, _user, *, start, end):
        return []

    monkeypatch.setattr(agent_tools, "_resolve_origin_address", fake_origin)
    monkeypatch.setattr(agent_tools.cal_service, "create_event", fake_create_event)
    monkeypatch.setattr(agent_tools.cal_service, "list_events", fake_list_events)

    ctx = ToolContext(
        session=_FakeSession(get_map={target_id: target}),
        user=user,
        proposal=ProposalSlot(),
    )
    tool = _get_tool(build_tools(ctx), "create_commute_event")

    result = await tool.coroutine(
        target_event_id=str(target_id),
        duration_minutes=20,
    )

    assert captured["title"] == "Дорога"
    assert captured["description"] is None
    assert result["route_url"] is None
    assert result["destination"] is None

@pytest.mark.asyncio
async def test_create_commute_event_rejects_bad_inputs(monkeypatch):
    user = _fake_user()
    ctx = ToolContext(
        session=_FakeSession(get_map={}),
        user=user,
        proposal=ProposalSlot(),
    )
    tool = _get_tool(build_tools(ctx), "create_commute_event")

    bad_id = await tool.coroutine(target_event_id="not-a-uuid", duration_minutes=10)
    assert "error" in bad_id

    zero = await tool.coroutine(target_event_id=str(uuid4()), duration_minutes=0)
    assert "error" in zero

    missing = await tool.coroutine(target_event_id=str(uuid4()), duration_minutes=15)
    assert "error" in missing
