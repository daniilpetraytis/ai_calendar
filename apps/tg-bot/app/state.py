"""In-memory per-user transient state, currently only the evening-feedback follow-up flow."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

@dataclass(slots=True)
class _Pending:
    """Pending evening-feedback score awaiting an optional follow-up text."""
    score: int
    expires_at: float

_pending: dict[int, _Pending] = {}
_lock = asyncio.Lock()

_TTL_SECONDS = 10 * 60  # 10 minutes — long enough to type a reply.

async def mark_awaiting_evening_text(telegram_user_id, *, score):
    """Remember that this user just rated the evening and may send a follow-up text."""
    async with _lock:
        _pending[telegram_user_id] = _Pending(
            score=score, expires_at=time.monotonic() + _TTL_SECONDS
        )

async def consume_awaiting_evening_text(telegram_user_id):
    """Pop and return the pending evening score for this user, or None if absent/expired."""
    async with _lock:
        entry = _pending.get(telegram_user_id)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            _pending.pop(telegram_user_id, None)
            return None
        _pending.pop(telegram_user_id, None)
        return entry.score

async def is_awaiting_evening_text(telegram_user_id):
    """Return True if this user has a non-expired pending evening-feedback follow-up."""
    async with _lock:
        entry = _pending.get(telegram_user_id)
        if entry is None:
            return False
        if entry.expires_at < time.monotonic():
            _pending.pop(telegram_user_id, None)
            return False
        return True
