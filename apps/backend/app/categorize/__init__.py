"""Default category catalog used to seed per-user category definitions."""

from __future__ import annotations

DEFAULT_CATEGORIES: list[dict] = [
    {"name": "work",     "color": "#3b82f6", "emoji": "💼"},
    {"name": "meeting",  "color": "#8b5cf6", "emoji": "👥"},
    {"name": "sport",    "color": "#10b981", "emoji": "🏃"},
    {"name": "health",   "color": "#ef4444", "emoji": "🏥"},
    {"name": "family",   "color": "#f59e0b", "emoji": "👨‍👩‍👧"},
    {"name": "hobby",    "color": "#ec4899", "emoji": "🎨"},
    {"name": "commute",  "color": "#6b7280", "emoji": "🚗"},
    {"name": "sleep",    "color": "#1f2937", "emoji": "😴"},
    {"name": "leisure",  "color": "#06b6d4", "emoji": "☕"},
    {"name": "personal", "color": "#a855f7", "emoji": "🧘"},
    {"name": "other",    "color": "#9ca3af", "emoji": "📌"},
]

VALID_CATEGORIES: frozenset[str] = frozenset(d["name"] for d in DEFAULT_CATEGORIES)
