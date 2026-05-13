"""LLM-based fallback classifier for events that rules could not categorize."""

from __future__ import annotations

import json
import logging
from uuid import UUID

from app.config import get_settings
from app.db.models import Event

log = logging.getLogger(__name__)

BATCH_SIZE = 20

_PROVIDER_DEFAULT_CHEAP: dict[str, str] = {
    "google": "gemini-2.5-flash",
    "anthropic": "claude-haiku-20240307",
    "openai": "gpt-4o-mini",
    "openrouter": "deepseek/deepseek-chat",
    "yandex": "yandexgpt-lite",
}

_CATEGORIES = (
    "work, meeting, sport, health, family, hobby, "
    "commute, sleep, leisure, personal, other"
)

_SYSTEM_PROMPT = (
    "You are an event classifier. Given a list of calendar events, "
    "classify each one into exactly one of these categories: "
    f"{_CATEGORIES}. "
    "Respond with a JSON array only, no markdown, no explanations. "
    'Format: [{"id": "...", "category": "...", "confidence": 0.0}]'
)

def _build_classifier_model():
    """Construct a LangChain chat model based on the configured LLM provider."""
    s = get_settings()
    model_name = s.classifier_model or _PROVIDER_DEFAULT_CHEAP.get(s.llm_provider, s.llm_model)

    if s.llm_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=s.google_api_key,
            temperature=0,
        )

    if s.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            api_key=s.anthropic_api_key,
            temperature=0,
            max_tokens=1024,
        )

    if s.llm_provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=s.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
        )

    if s.llm_provider == "yandex":
        from langchain_openai import ChatOpenAI
        model = model_name
        if not model.startswith("gpt://"):
            model = f"gpt://{s.yandex_folder_id}/{model_name}"
        return ChatOpenAI(
            model=model,
            api_key=s.yandex_api_key,
            base_url=s.yandex_base_url,
            default_headers={"x-folder-id": s.yandex_folder_id},
            temperature=0,
        )

    # openai (default)
    from langchain_openai import ChatOpenAI
    kwargs = {"model": model_name, "api_key": s.openai_api_key, "temperature": 0}
    if s.openai_base_url:
        kwargs["base_url"] = s.openai_base_url
    return ChatOpenAI(**kwargs)

async def classify_with_llm(events):
    """Classify events in batches via the configured LLM and return a mapping of event id to (category, confidence)."""
    results = {}
    if not events:
        return results

    llm = _build_classifier_model()

    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i : i + BATCH_SIZE]
        items = [
            {
                "id": str(e.id),
                "title": e.title,
                "description": (e.description or "")[:200],
                "location": (e.location or "")[:100],
                "start_hour": e.start_at.hour,
                "weekday": e.start_at.strftime("%A"),
            }
            for e in batch
        ]
        user_msg = json.dumps(items, ensure_ascii=False)

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            response = await llm.ainvoke(
                [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
            )
            raw = response.content
            # Strip possible markdown fences
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
        except Exception as exc:
            log.warning("llm_classify_batch_failed", extra={"error": str(exc), "batch_size": len(batch)})
            continue

        valid_categories = {
            "work", "meeting", "sport", "health", "family",
            "hobby", "commute", "sleep", "leisure", "personal", "other",
        }
        id_map = {str(e.id): e.id for e in batch}
        for item in parsed:
            try:
                eid = item["id"]
                cat = item["category"]
                conf = float(item.get("confidence", 0.7))
                if eid in id_map and cat in valid_categories:
                    results[id_map[eid]] = (cat, min(max(conf, 0.0), 1.0))
            except (KeyError, TypeError, ValueError):
                continue

    return results
