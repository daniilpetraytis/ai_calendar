"""Keyword-based event categorization rules with bilingual (RU/EN) vocabularies."""

from __future__ import annotations

from datetime import datetime

_SPORT_KEYWORDS = [
    "тренировк", "пробежк", "пробег",
    "качалка", "зал", "фитнес", "gym",
    "йога", "yoga", "пилатес", "pilates",
    "workout", "run", "бег",
    "crossfit", "кроссфит",
    "плавание", "swim", "велосипед", "cycling",
    "теннис", "tennis", "футбол", "football",
    "баскетбол", "basketball",
]

_COMMUTE_KEYWORDS = [
    "такси", "uber", "яндекс такси",
    "поезд", "электричка", "метро", "автобус",
    "самолёт", "рейс", "flight", "аэропорт", "airport",
    "поездка", "trip", "дорога", "road",
]

_RULES: list[tuple[str, list[str], float]] = [
    (
        "meeting",
        [
            "zoom", "meet", "teams", "webex", "skype", "hangout",
            "created", "созвон", "встреча", "звонок",
            "интервью", "interview",
            "1on1", "1:1", "one-on-one",
            "standup", "stand-up", "стендап",
            "sync", "synс",       # ascii and cyrillic с
            "ретро", "retro", "планёрка", "совещание",
        ],
        0.80,
    ),
    (
        "sport",
        _SPORT_KEYWORDS,
        0.80,
    ),
    (
        "health",
        [
            "врач", "доктор", "клиника", "больниц", "поликлиник",
            "анализ", "анализы", "мрт", "узи",
            "терапевт", "хирург", "кардиолог", "невролог",
            "стоматолог", "dentist", "doctor", "hospital",
            "аптека", "pharmacy", "вакцин", "vaccine",
        ],
        0.80,
    ),
    (
        "commute",
        _COMMUTE_KEYWORDS,
        0.75,
    ),
    (
        "leisure",
        [
            "обед", "ужин", "завтрак", "перекус",
            "кофе", "coffee", "чай",
            "бар", "ресторан", "кафе", "restaurant", "cafe",
            "lunch", "dinner", "breakfast", "brunch",
        ],
        0.75,
    ),
    (
        "family",
        [
            "семья", "родители", "мама", "папа", "бабушка", "дедушка",
            "жена", "муж", "дети", "ребёнок", "ребенок",
            "семейн", "family",
        ],
        0.75,
    ),
    (
        "work",
        [
            "работ", "офис",
            "deadline", "дедлайн",
            "review", "ревью", "код-ревью", "code review",
            "планирование", "проект", "project",
            "задача", "задачи", "релиз", "release",
            "спринт", "sprint", "бэклог", "backlog",
        ],
        0.70,
    ),
    (
        "personal",
        [
            "медитац", "meditation",
            "дневник", "journal",
            "личн", "personal",
            "саморазвит", "self-development",
        ],
        0.70,
    ),
    (
        "hobby",
        [
            "хобби", "hobby",
            "рисован", "drawing", "painting",
            "музык", "music", "гитар", "guitar",
            "кино", "movie", "фильм", "сериал",
            "книг", "book", "чтени",
            "игр", "game", "gaming",
        ],
        0.70,
    ),
]

def classify_by_rules(
    title,
    description,
    location,
    start,
    end,
):
    """Classify an event by simple time-of-day and keyword rules, returning ``(category, confidence)`` or ``None``."""
    hour = start.hour
    if hour >= 23 or hour < 6:
        return ("sleep", 0.95)

    title_text = (title or "").lower()

    if any(kw in title_text for kw in _COMMUTE_KEYWORDS):
        return ("commute", 0.80)

    text = " ".join(
        filter(None, [title, description or "", location or ""])
    ).lower()

    for category, keywords, confidence in _RULES:
        if any(kw in text for kw in keywords):
            return (category, confidence)

    return None
