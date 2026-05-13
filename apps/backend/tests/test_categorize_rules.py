"""Tests for the rule-based event categorizer (commute vs sport disambiguation)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.categorize.rules import classify_by_rules

def _dt():
    return datetime(2026, 5, 10, 11, 0, tzinfo=timezone.utc)

def test_commute_title_has_priority_over_destination_keywords():
    result = classify_by_rules(
        title="Дорога на тренировку с реабилитологом",
        description=None,
        location=None,
        start=_dt(),
        end=_dt(),
    )
    assert result == ("commute", 0.80)

def test_sport_without_commute_cues_stays_sport():
    result = classify_by_rules(
        title="Тренировка с реабилитологом",
        description=None,
        location=None,
        start=_dt(),
        end=_dt(),
    )
    assert result == ("sport", 0.80)
