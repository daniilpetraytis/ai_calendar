"""LangGraph agent.

We use the prebuilt ``create_react_agent`` for the agent loop because it gives
us a battle-tested ReAct-style implementation with tool-calling and streaming
out of the box. The HITL approval flow lives one layer up in
``app.agent.runner``: the agent calls ``propose_replan`` (a non-applying tool),
the runner detects that a proposal was attached, and stops the run with status
``awaiting_approval``. The user-approved diff is then applied by ``app.api.replan``.

This keeps the graph itself simple while providing a strong correctness guarantee
about destructive operations (multi-event changes always go through approval).

Provider matrix (set ``LLM_PROVIDER`` in env):

- ``anthropic`` — Claude (e.g. ``claude-sonnet-4-5-20250929``). Excellent tool-calling.
- ``google`` — Gemini (e.g. ``gemini-2.5-pro``, ``gemini-2.5-flash``). Solid tool-calling
  and a generous free tier; signup at https://aistudio.google.com. **Default.**
- ``openai`` — GPT models (e.g. ``gpt-5``, ``gpt-4o``). Set ``OPENAI_BASE_URL`` to use
  any OpenAI-compatible endpoint (e.g. local Ollama, Together, Fireworks).
- ``openrouter`` — single key, any model: set ``LLM_MODEL`` to e.g.
  ``anthropic/claude-sonnet-4.5`` or ``deepseek/deepseek-chat``.
- ``yandex`` — Yandex AI Studio (YandexGPT Pro / Qwen3 235B / gpt-oss-120b / Gemma 3).
  Requires ``YANDEX_API_KEY`` and ``YANDEX_FOLDER_ID``. Pay-per-token in roubles.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from app.config import get_settings


def build_chat_model() -> BaseChatModel:
    s = get_settings()
    timeout = s.llm_request_timeout_seconds

    if s.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if not s.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return ChatAnthropic(
            model=s.llm_model,
            api_key=s.anthropic_api_key,
            temperature=0,
            max_tokens=2048,
            timeout=timeout,
        )

    if s.llm_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not s.google_api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Get a free key at https://aistudio.google.com"
            )
        return ChatGoogleGenerativeAI(
            model=s.llm_model,
            google_api_key=s.google_api_key,
            temperature=0,
            timeout=timeout,
        )

    if s.llm_provider == "openrouter":
        from langchain_openai import ChatOpenAI

        if not s.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        return ChatOpenAI(
            model=s.llm_model,
            api_key=s.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
            timeout=timeout,
        )

    if s.llm_provider == "yandex":
        from langchain_openai import ChatOpenAI

        if not s.yandex_api_key:
            raise RuntimeError("YANDEX_API_KEY is not set")
        if not s.yandex_folder_id:
            raise RuntimeError("YANDEX_FOLDER_ID is not set")
        # Yandex expects model identifier in the form ``gpt://<folder_id>/<name>``.
        # Accept both: explicit URI passed via LLM_MODEL, or short name we expand.
        model = s.llm_model
        if not model.startswith(("gpt://", "emb://")):
            model = f"gpt://{s.yandex_folder_id}/{model}"
        headers: dict[str, str] = {"x-folder-id": s.yandex_folder_id}
        if s.yandex_disable_logging:
            headers["x-data-logging-enabled"] = "false"
        return ChatOpenAI(
            model=model,
            api_key=s.yandex_api_key,
            base_url=s.yandex_base_url,
            default_headers=headers,
            temperature=0,
            timeout=timeout,
        )

    from langchain_openai import ChatOpenAI

    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    kwargs: dict = {
        "model": s.llm_model,
        "api_key": s.openai_api_key,
        "temperature": 0,
        "timeout": timeout,
    }
    if s.openai_base_url:
        kwargs["base_url"] = s.openai_base_url
    return ChatOpenAI(**kwargs)


def build_agent(tools: list[StructuredTool], system_prompt: str):
    """Build the prebuilt ReAct agent. Returns a compiled graph."""
    llm = build_chat_model()
    return create_react_agent(model=llm, tools=tools, prompt=system_prompt)
