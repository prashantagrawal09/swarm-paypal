"""Relays agent messages addressed to owners into their linked Telegram chats.

It subscribes to the message bus, so anything a shop agent says to `owner:<code>` (Monday
forecast, award news, delivery check, swap offers, refunds, reports...) reaches the owner,
with its action buttons as an inline keyboard.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from sqlalchemy import select
from telegram import InlineKeyboardMarkup

from app.agents.bus import BusEvent
from app.db.models import Shop
from app.db.session import get_sessionmaker
from app.runtime import Runtime
from app.telegram_bot.keyboards import keyboard

logger = logging.getLogger(__name__)


class Sender(Protocol):
    async def send_message(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> Any: ...


def format_text(shop: Shop, text: str, demo_mode: bool) -> str:
    return f"🏪 {shop.name}\n{text}" if demo_mode else text


class TelegramNotifier:
    def __init__(self, runtime: Runtime, sender: Sender) -> None:
        self.runtime = runtime
        self.sender = sender
        self._queue: asyncio.Queue[BusEvent] | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._queue = self.runtime.bus.subscribe()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._queue:
            self.runtime.bus.unsubscribe(self._queue)

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                await self.handle(event)
            except Exception:
                logger.exception("Could not relay a message to Telegram")

    async def handle(self, event: BusEvent) -> bool:
        if event.event != "agent_message":
            return False
        to = str(event.data.get("to", ""))
        if not to.startswith("owner:"):
            return False
        code = to.split(":", 1)[1]
        async with get_sessionmaker()() as session:
            shop = await session.scalar(select(Shop).where(Shop.code == code))
        if shop is None or shop.telegram_chat_id is None:
            return False
        payload = event.data.get("payload") or {}
        actions = [] if payload.get("answered") else payload.get("actions", [])
        await self.sender.send_message(
            shop.telegram_chat_id,
            format_text(shop, str(event.data.get("text", "")), self.runtime.settings.demo_mode),
            reply_markup=keyboard(shop.code, actions),
        )
        return True
