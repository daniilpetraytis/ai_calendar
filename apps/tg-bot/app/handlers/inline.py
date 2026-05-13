"""Callback-query router: Apply / Reject proposal buttons and evening-feedback chips."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app import backend_client, state

log = logging.getLogger(__name__)

router = Router(name="inline")

@router.callback_query(F.data.startswith("apply:"))
async def cb_apply(cq):
    """Handle the "Apply" button on a proposal card and report the result."""
    if cq.data is None or cq.from_user is None:
        await cq.answer()
        return
    run_id = cq.data.split(":", 1)[1]

    try:
        result = await backend_client.apply_proposal(
            cq.from_user.id, run_id, approve=True
        )
    except backend_client.BackendError as exc:
        await cq.answer(f"Ошибка: {exc.message}"[:200], show_alert=True)
        return

    applied = result.get("applied", 0)
    errors = result.get("errors") or []
    suffix = f"\n\n✅ Применено: {applied}."
    if errors:
        suffix += f" Не получилось: {len(errors)}."
    if cq.message is not None:
        try:
            base = cq.message.text or ""
            await cq.message.edit_text(base + suffix, reply_markup=None)
        except Exception:
            await cq.message.answer(suffix.strip())
    await cq.answer("Применено")

@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(cq):
    """Handle the "Reject" button on a proposal card and mark the run rejected."""
    if cq.data is None or cq.from_user is None:
        await cq.answer()
        return
    run_id = cq.data.split(":", 1)[1]
    try:
        await backend_client.apply_proposal(
            cq.from_user.id, run_id, approve=False
        )
    except backend_client.BackendError as exc:
        await cq.answer(f"Ошибка: {exc.message}"[:200], show_alert=True)
        return

    if cq.message is not None:
        try:
            base = cq.message.text or ""
            await cq.message.edit_text(base + "\n\n❌ Отклонено.", reply_markup=None)
        except Exception:
            await cq.message.answer("Отклонено.")
    await cq.answer("Отклонено")

_EVE_LABELS = {1: "😴 легко", 2: "🙂 ок", 3: "🥵 тяжко"}

@router.callback_query(F.data.startswith("eve:"))
async def cb_evening_feedback(cq):
    """Handle an evening-feedback emoji vote and prompt for an optional follow-up note."""
    if cq.data is None or cq.from_user is None:
        await cq.answer()
        return
    raw = cq.data.split(":", 1)[1]
    try:
        score = int(raw)
    except ValueError:
        await cq.answer()
        return
    if score not in (1, 2, 3):
        await cq.answer()
        return

    try:
        await backend_client.post_evening_feedback(cq.from_user.id, score=score)
    except backend_client.NotLinkedError:
        await cq.answer("Аккаунт не привязан", show_alert=True)
        return
    except backend_client.BackendError as exc:
        await cq.answer(f"Ошибка: {exc.message}"[:200], show_alert=True)
        return

    await state.mark_awaiting_evening_text(cq.from_user.id, score=score)

    if cq.message is not None:
        label = _EVE_LABELS.get(score, str(score))
        try:
            base = cq.message.text or "Как день?"
            await cq.message.edit_text(
                f"{base}\n\n→ {label}.\nХочешь добавить пару слов? Напиши следующим сообщением.",
                reply_markup=None,
            )
        except Exception:
            await cq.message.answer(f"Записал: {label}. Можешь добавить мысль текстом.")
    await cq.answer("Спасибо!")
