"""Tests for the agent runner's user-facing write-confirmation messages."""

from app.agent.runner import _build_write_confirmation

def test_build_write_confirmation_uses_updated_event_times():
    payload = {
        "updated_event": {
            "title": "Работа над дипломом",
            "start_iso": "2026-05-10T22:23:00+03:00",
            "end_iso": "2026-05-10T23:38:00+03:00",
        },
        "conflicts": [],
    }
    msg = _build_write_confirmation("move_event", payload)
    assert msg == "«Работа над дипломом» перенесено на 22:23–23:38. Конфликтов нет."

def test_build_write_confirmation_lists_conflicts():
    payload = {
        "updated_event": {
            "title": "Тренировка",
            "start_iso": "2026-05-10T21:00:00+03:00",
            "end_iso": "2026-05-10T22:00:00+03:00",
        },
        "conflicts": [
            {
                "title": "Ужин",
                "start_iso": "2026-05-10T21:30:00+03:00",
                "end_iso": "2026-05-10T22:00:00+03:00",
            }
        ],
    }
    msg = _build_write_confirmation("shift_event", payload)
    assert msg == "«Тренировка» перенесено на 21:00–22:00. Есть конфликты: «Ужин» (21:30–22:00)."
