"""The Telegram bot, running inside the API process (so it sees the same message bus).

- Production (PUBLIC_BACKEND_URL is https): webhook. Telegram posts updates to
  `/telegram/webhook`, authenticated with TELEGRAM_WEBHOOK_SECRET.
- Local development: long polling, no public URL needed.
Without TELEGRAM_BOT_TOKEN the bot is off and owners use the web phone in the demo panel.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from telegram import BotCommand, Update
from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.runtime import Runtime, get_runtime
from app.telegram_bot import handlers
from app.telegram_bot.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])

COMMANDS = [
    BotCommand("start", "Link this chat to your shop: /start <shop code>"),
    BotCommand("report", "This week's savings"),
    BotCommand("help", "What you can ask me"),
    BotCommand("as", "Demo: act as another shop"),
    BotCommand("shops", "Demo: list the shops"),
]


@dataclass
class BotRuntime:
    application: Application[Any, Any, Any, Any, Any, Any]
    notifier: TelegramNotifier
    webhook: bool


def build_application(token: str, runtime: Runtime) -> Application[Any, Any, Any, Any, Any, Any]:
    application = Application.builder().token(token).rate_limiter(AIORateLimiter()).build()
    application.bot_data["runtime"] = runtime
    application.add_handler(CommandHandler("start", handlers.on_start))
    application.add_handler(CommandHandler("as", handlers.on_as))
    application.add_handler(CommandHandler("shops", handlers.on_shops))
    application.add_handler(CommandHandler("report", handlers.on_report))
    application.add_handler(CommandHandler("help", handlers.on_help))
    application.add_handler(CallbackQueryHandler(handlers.on_button))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.on_photo))
    application.add_handler(MessageHandler(filters.VOICE, handlers.on_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))
    return application


async def start_bot(runtime: Runtime) -> BotRuntime | None:
    settings = runtime.settings
    if not settings.telegram_bot_token:
        logger.info("Telegram bot off (no TELEGRAM_BOT_TOKEN)")
        return None
    application = build_application(settings.telegram_bot_token.get_secret_value(), runtime)
    await application.initialize()
    await application.start()
    webhook = settings.public_backend_url.startswith("https://")
    if webhook:
        secret = (
            settings.telegram_webhook_secret.get_secret_value()
            if settings.telegram_webhook_secret
            else None
        )
        await application.bot.set_webhook(
            f"{settings.public_backend_url.rstrip('/')}/telegram/webhook",
            secret_token=secret,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        await application.bot.delete_webhook()
        assert application.updater is not None
        await application.updater.start_polling(drop_pending_updates=True)
    await application.bot.set_my_commands(COMMANDS)
    notifier = TelegramNotifier(runtime, application.bot)
    notifier.start()
    logger.info("Telegram bot running (%s)", "webhook" if webhook else "polling")
    return BotRuntime(application, notifier, webhook)


async def stop_bot(bot: BotRuntime | None) -> None:
    if bot is None:
        return
    await bot.notifier.stop()
    if bot.application.updater and bot.application.updater.running:
        await bot.application.updater.stop()
    await bot.application.stop()
    await bot.application.shutdown()


def runtime_dep() -> Runtime:
    return get_runtime()


@router.post("/telegram/webhook")
async def webhook(
    request: Request,
    runtime: Annotated[Runtime, Depends(runtime_dep)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    bot: BotRuntime | None = getattr(request.app.state, "telegram", None)
    if bot is None:
        raise HTTPException(status_code=503, detail="Telegram bot is not running")
    expected = runtime.settings.telegram_webhook_secret
    if expected is not None and not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", expected.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Bad webhook secret")
    update = Update.de_json(await request.json(), bot.application.bot)
    await bot.application.process_update(update)
    return {"ok": True}
