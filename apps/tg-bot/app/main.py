"""Entry point for the Telegram bot: wires routers, push server, and polling/webhook loop."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

import structlog
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_bot_settings
from app.handlers import chat as chat_handler
from app.handlers import commands as commands_handler
from app.handlers import inline as inline_handler
from app.handlers import start as start_handler
from app.handlers import voice as voice_handler
from app.push_server import build_push_app

def _configure_logging(level):
    """Configure stdlib logging and structlog for the bot process."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram").setLevel("INFO")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

async def _log_every_update(handler, event, data):  # type: ignore[no-untyped-def]
    """Outer middleware that logs a one-line summary of every incoming update."""
    log = logging.getLogger("tg-update")
    summary = "?"
    try:
        if hasattr(event, "message") and event.message is not None:
            m = event.message
            who = m.from_user.id if m.from_user else "?"
            summary = f"message from={who} text={(m.text or m.caption or '<non-text>')[:80]!r}"
        elif hasattr(event, "callback_query") and event.callback_query is not None:
            cq = event.callback_query
            who = cq.from_user.id if cq.from_user else "?"
            summary = f"callback_query from={who} data={cq.data!r}"
        else:
            summary = f"update kind={type(event).__name__}"
    except Exception:
        pass
    log.info("incoming: %s", summary)
    return await handler(event, data)

async def _run_polling(bot, dp):
    """Run the bot using long polling, removing any previously set webhook first."""
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)

async def _run_webhook(bot, dp):
    """Run the bot in webhook mode behind an aiohttp server."""
    from aiogram.webhook.aiohttp_server import (
        SimpleRequestHandler,
        setup_application,
    )
    from aiohttp import web

    settings = get_bot_settings()
    if not settings.tg_webhook_url:
        raise RuntimeError("TG_BOT_MODE=webhook requires TG_WEBHOOK_URL")

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=settings.tg_webhook_secret or None
    ).register(app, path="/telegram/webhook")
    setup_application(app, dp, bot=bot)
    await bot.set_webhook(
        settings.tg_webhook_url,
        secret_token=settings.tg_webhook_secret or None,
        drop_pending_updates=False,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.push_listen_host, settings.push_listen_port + 1)
    await site.start()
    while True:
        await asyncio.sleep(3600)

async def main():
    """Bootstrap settings, build the bot and push server, and run them concurrently."""
    settings = get_bot_settings()
    _configure_logging(settings.log_level)
    log = logging.getLogger("tg-bot")

    if not settings.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN is not set; bot will not start.")
        raise SystemExit(1)
    if not settings.internal_service_token:
        log.error("INTERNAL_SERVICE_TOKEN is not set; refusing to start (would talk to backend insecurely).")
        raise SystemExit(1)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()
    dp.update.outer_middleware(_log_every_update)
    dp.include_router(start_handler.router)
    dp.include_router(commands_handler.router)
    dp.include_router(inline_handler.router)
    dp.include_router(voice_handler.router)
    dp.include_router(chat_handler.router)

    push_app = build_push_app(bot)
    push_config = uvicorn.Config(
        push_app,
        host=settings.push_listen_host,
        port=settings.push_listen_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    push_server = uvicorn.Server(push_config)

    if settings.tg_bot_mode == "webhook":
        bot_task = asyncio.create_task(_run_webhook(bot, dp), name="tg-webhook")
    else:
        bot_task = asyncio.create_task(_run_polling(bot, dp), name="tg-polling")
    push_task = asyncio.create_task(push_server.serve(), name="push-server")

    log.info(
        "tg-bot started (mode=%s, push_port=%s)",
        settings.tg_bot_mode,
        settings.push_listen_port,
    )

    done, pending = await asyncio.wait(
        {bot_task, push_task}, return_when=asyncio.FIRST_EXCEPTION
    )
    for task in pending:
        task.cancel()
    for task in done:
        if task.exception() is not None:
            raise task.exception()  # type: ignore[misc]

if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
